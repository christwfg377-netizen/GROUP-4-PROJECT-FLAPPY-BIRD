import difflib
import hashlib
import json
import re
import tkinter as tk
from datetime import datetime
from itertools import combinations
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
except ImportError as error:
    raise SystemExit("customtkinter is required. Install it with: pip install customtkinter") from error


APP_TITLE = "Document Plagiarism & Similarity Checker"
ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}
MAX_FILE_SIZE = 25 * 1024 * 1024
ASSETS_DIR = Path("assets")
REPORTS_DIR = Path("reports")
HISTORY_FILE = Path("history.json")
INTERNAL_DB_DIR = Path("internal_db")
SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")
WORD_RE = re.compile(r"[a-zA-Z0-9']+")

THEMES = {
    "dark": {
        "sidebar_bg": "#0d0d1a", "panel_bg": "#12121f", "card_bg": "#1a1a2e",
        "accent": "#a855f7", "muted_text": "#a0aec0", "title_text": "#f0e6ff",
        "button_bg": "#7c3aed", "hover_bg": "#6d28d9", "border": "#2d2d4e",
        "topbar_bg": "#0d0d1a", "topbar_fg": "#f0e6ff",
        "status_bg": "#0d0d1a", "status_fg": "#a0aec0",
        "input_bg": "#1e1e35", "input_fg": "#f0e6ff",
    },
}

ASSETS_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)
INTERNAL_DB_DIR.mkdir(exist_ok=True)


# -----------------------------
# Utility and text processing
# -----------------------------
def clean_text(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_sentences(text):
    sentences = [sentence.strip() for sentence in SENTENCE_RE.findall(text)]
    return [sentence for sentence in sentences if len(sentence.split()) > 2]


def split_paragraphs(text):
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", text)]
    return [paragraph for paragraph in paragraphs if paragraph]


def word_frequency(text, limit=15):
    counts = {}
    for word in WORD_RE.findall(clean_text(text)):
        if len(word) < 3:
            continue
        counts[word] = counts.get(word, 0) + 1
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]


def document_stats(text):
    words = WORD_RE.findall(text)
    clean_words = WORD_RE.findall(clean_text(text))
    return {
        "word_count": len(words),
        "character_count": len(text),
        "sentence_count": len(split_sentences(text)),
        "paragraph_count": len(split_paragraphs(text)),
        "unique_word_count": len(set(clean_words)),
    }


def sha256_fingerprint(text):
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def safe_percent(value):
    return max(0, min(100, round(value * 100, 1)))


def create_manual_document(text, name="Manual Document", source="Manual entry"):
    size_bytes = len(text.encode("utf-8"))
    return {
        "path": f"<{name.lower().replace(' ', '-')}>",
        "name": name,
        "extension": ".txt",
        "size_bytes": size_bytes,
        "size": format_size(size_bytes),
        "text": text,
        "stats": document_stats(text),
        "fingerprint": sha256_fingerprint(text),
        "source": source,
    }


# -----------------------------
# Safe file loading
# -----------------------------
def validate_file(path):
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise ValueError("File does not exist.")
    if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Only TXT, PDF, and DOCX files are supported.")
    if file_path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("File is too large. Maximum size is 25 MB.")
    return file_path


def extract_txt(file_path):
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return file_path.read_text(encoding="latin-1")


def extract_pdf(file_path):
    try:
        from PyPDF2 import PdfReader
    except ImportError as error:
        raise ImportError("PyPDF2 is required to read PDF files.") from error

    reader = PdfReader(str(file_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_docx(file_path):
    try:
        from docx import Document
    except ImportError as error:
        raise ImportError("python-docx is required to read DOCX files.") from error

    document = Document(str(file_path))
    return "\n\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_text(file_path):
    extension = file_path.suffix.lower()
    if extension == ".txt":
        return extract_txt(file_path)
    if extension == ".pdf":
        return extract_pdf(file_path)
    if extension == ".docx":
        return extract_docx(file_path)
    raise ValueError("Unsupported file type.")


def load_document(path):
    file_path = validate_file(path)
    text = extract_text(file_path)
    if not text.strip():
        raise ValueError("No readable text was found in this file.")

    size = file_path.stat().st_size
    return {
        "path": str(file_path),
        "name": file_path.name,
        "extension": file_path.suffix.lower(),
        "size_bytes": size,
        "size": format_size(size),
        "text": text,
        "stats": document_stats(text),
        "fingerprint": sha256_fingerprint(text),
    }


def load_internal_database():
    documents = []
    if not INTERNAL_DB_DIR.exists():
        return documents

    for entry in sorted(INTERNAL_DB_DIR.iterdir()):
        if entry.is_file() and entry.suffix.lower() in ALLOWED_EXTENSIONS:
            try:
                documents.append(load_document(entry))
            except (ValueError, ImportError, OSError):
                continue
    return documents


def check_online_sources(text, start_index=1):
    if not text.strip():
        return []

    example_sentence = next((sentence for sentence in split_sentences(text) if len(sentence.split()) >= 8), text.strip()[:200])
    similarity = 0.16
    return [
        {
            "left_index": 0,
            "right_index": start_index,
            "left_name": "Primary Document",
            "right_name": "Online Source",
            "source": "Online search placeholder",
            "similarity": safe_percent(similarity),
            "raw_similarity": similarity,
            "plagiarism": 0,
            "sentence_matches": [],
            "paragraph_matches": [],
            "paraphrase_matches": [],
        }
    ]


def fuzzy_sentence_matches(text_a, text_b, threshold=0.72):
    sentences_a = split_sentences(text_a)
    sentences_b = split_sentences(text_b)
    matches = []
    seen = set()

    for sentence_a in sentences_a:
        cleaned_a = clean_text(sentence_a)
        if not cleaned_a:
            continue

        best_match = None
        best_ratio = 0.0
        for sentence_b in sentences_b:
            cleaned_b = clean_text(sentence_b)
            if not cleaned_b or cleaned_a == cleaned_b:
                continue
            ratio = difflib.SequenceMatcher(None, cleaned_a, cleaned_b).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = sentence_b

        if best_match and best_ratio >= threshold:
            key = (cleaned_a, clean_text(best_match))
            if key not in seen:
                seen.add(key)
                matches.append({"a": sentence_a, "b": best_match, "score": round(best_ratio * 100, 1)})

    return matches


# -----------------------------
# Similarity and plagiarism engine
# -----------------------------
def load_sklearn():
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as error:
        raise ImportError("scikit-learn is required for TF-IDF similarity detection.") from error
    return TfidfVectorizer, cosine_similarity


def tfidf_similarity(texts):
    if len(texts) < 2:
        return []

    TfidfVectorizer, cosine_similarity = load_sklearn()
    cleaned = [clean_text(text) for text in texts]
    matrix = TfidfVectorizer(stop_words="english").fit_transform(cleaned)
    similarity_matrix = cosine_similarity(matrix)

    scores = []
    for left, right in combinations(range(len(texts)), 2):
        scores.append({"left": left, "right": right, "score": float(similarity_matrix[left][right])})
    return scores


def exact_sentence_matches(text_a, text_b):
    original_a = split_sentences(text_a)
    original_b = split_sentences(text_b)
    lookup_b = {clean_text(sentence): sentence for sentence in original_b}
    matches = []
    seen = set()

    for sentence in original_a:
        key = clean_text(sentence)
        if key and key in lookup_b and key not in seen:
            matches.append({"a": sentence, "b": lookup_b[key], "clean": key})
            seen.add(key)
    return matches


def paragraph_matches(text_a, text_b):
    paragraphs_a = split_paragraphs(text_a)
    paragraphs_b = split_paragraphs(text_b)
    lookup_b = {clean_text(paragraph): paragraph for paragraph in paragraphs_b}
    matches = []

    for paragraph in paragraphs_a:
        key = clean_text(paragraph)
        if len(key.split()) >= 8 and key in lookup_b:
            matches.append({"a": paragraph, "b": lookup_b[key], "clean": key})
    return matches


def repeated_sentences(text):
    counts = {}
    originals = {}
    for sentence in split_sentences(text):
        key = clean_text(sentence)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
        originals.setdefault(key, sentence)
    return [{"sentence": originals[key], "count": count} for key, count in counts.items() if count > 1]


def plagiarism_percentage(text, sentence_matches, paragraph_matches_found):
    total_sentences = max(1, len(split_sentences(text)))
    matched_sentences = len(sentence_matches)
    paragraph_sentence_bonus = sum(len(split_sentences(match["a"])) for match in paragraph_matches_found)
    return safe_percent((matched_sentences + paragraph_sentence_bonus) / total_sentences)


def compare_documents(documents, focus_index=None):
    texts = [document["text"] for document in documents]
    scores = tfidf_similarity(texts)
    comparisons = []

    for score in scores:
        if focus_index is not None and focus_index not in (score["left"], score["right"]):
            continue
        left_doc = documents[score["left"]]
        right_doc = documents[score["right"]]
        sentence_matches = exact_sentence_matches(left_doc["text"], right_doc["text"])
        paragraphs = paragraph_matches(left_doc["text"], right_doc["text"])
        paraphrase_matches = fuzzy_sentence_matches(left_doc["text"], right_doc["text"])
        source = None
        if focus_index is not None:
            source = right_doc["name"] if score["left"] == focus_index else left_doc["name"]

        comparisons.append(
            {
                "left_index": score["left"],
                "right_index": score["right"],
                "left_name": left_doc["name"],
                "right_name": right_doc["name"],
                "source": source,
                "similarity": safe_percent(score["score"]),
                "raw_similarity": score["score"],
                "plagiarism": plagiarism_percentage(left_doc["text"], sentence_matches, paragraphs),
                "sentence_matches": sentence_matches,
                "paragraph_matches": paragraphs,
                "paraphrase_matches": paraphrase_matches,
            }
        )

    average_similarity = round(
        sum(comparison["similarity"] for comparison in comparisons) / len(comparisons), 1
    ) if comparisons else 0

    return {
        "documents": documents,
        "comparisons": comparisons,
        "average_similarity": average_similarity,
        "duplicates": [repeated_sentences(document["text"]) for document in documents],
        "word_frequency": word_frequency(" ".join(texts)),
        "stats": [document_stats(text) for text in texts],
    }


def analyze_single_document(document):
    internal_docs = load_internal_database()
    comparisons = []
    for internal_doc in internal_docs:
        sentence_matches = exact_sentence_matches(document["text"], internal_doc["text"])
        paragraphs = paragraph_matches(document["text"], internal_doc["text"])
        paraphrase_matches = fuzzy_sentence_matches(document["text"], internal_doc["text"])
        score = tfidf_similarity([document["text"], internal_doc["text"]])[0]["score"] if internal_docs else 0
        comparisons.append(
            {
                "left_index": 0,
                "right_index": 1,
                "left_name": document["name"],
                "right_name": internal_doc["name"],
                "source": internal_doc["name"],
                "similarity": safe_percent(score),
                "raw_similarity": score,
                "plagiarism": plagiarism_percentage(document["text"], sentence_matches, paragraphs),
                "sentence_matches": sentence_matches,
                "paragraph_matches": paragraphs,
                "paraphrase_matches": paraphrase_matches,
            }
        )

    online_matches = check_online_sources(document["text"])
    comparisons.extend(online_matches)
    average_similarity = round(sum(comparison["similarity"] for comparison in comparisons) / len(comparisons), 1) if comparisons else 0

    return {
        "documents": [document],
        "comparisons": comparisons,
        "average_similarity": average_similarity,
        "duplicates": [repeated_sentences(document["text"])],
        "word_frequency": word_frequency(document["text"]),
        "stats": [document_stats(document["text"])],
    }


# -----------------------------
# History, charts, and reports
# -----------------------------
def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_history(records):
    HISTORY_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")


def add_history_record(result):
    records = load_history()
    record = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": [document["name"] for document in result["documents"]],
        "total_files": len(result["documents"]),
        "average_similarity": result["average_similarity"],
        "comparisons": [
            {
                "left_name": comparison["left_name"],
                "right_name": comparison["right_name"],
                "similarity": comparison["similarity"],
                "plagiarism": comparison["plagiarism"],
            }
            for comparison in result["comparisons"]
        ],
    }
    records.insert(0, record)
    save_history(records[:100])
    return record


def load_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise ImportError("matplotlib is required to generate charts.") from error
    return plt


def create_pie_chart(similarity, output_path=None):
    plt = load_matplotlib()
    output = Path(output_path or ASSETS_DIR / "content_pie.png")
    unique = max(0, 100 - similarity)
    fig, ax = plt.subplots(figsize=(4, 3), facecolor="#ffffff")
    ax.pie(
        [unique, similarity],
        labels=["Unique", "Similar"],
        autopct="%1.1f%%",
        colors=["#3b82f6", "#ef4444"],
        textprops={"color": "#1e293b", "fontsize": 9},
    )
    ax.set_title("Unique vs Similar Content", color="#1e293b")
    ax.set_facecolor("#ffffff")
    fig.tight_layout()
    fig.savefig(output, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    return str(output)


def create_bar_chart(comparisons, output_path=None):
    plt = load_matplotlib()
    output = Path(output_path or ASSETS_DIR / "similarity_bar.png")
    labels = [f"{item['left_index'] + 1}-{item['right_index'] + 1}" for item in comparisons] or ["No data"]
    values = [item["similarity"] for item in comparisons] or [0]
    fig, ax = plt.subplots(figsize=(5, 3), facecolor="#ffffff")
    ax.bar(labels, values, color="#3b82f6")
    ax.set_ylim(0, 100)
    ax.set_ylabel("Similarity %", color="#1e293b")
    ax.set_title("Similarity Scores", color="#1e293b")
    ax.tick_params(colors="#475569")
    ax.set_facecolor("#f8fafc")
    fig.tight_layout()
    fig.savefig(output, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    return str(output)


def create_word_frequency_chart(frequencies, output_path=None):
    plt = load_matplotlib()
    output = Path(output_path or ASSETS_DIR / "word_frequency.png")
    labels = [word for word, count in frequencies] or ["No data"]
    values = [count for word, count in frequencies] or [0]
    fig, ax = plt.subplots(figsize=(5, 3), facecolor="#ffffff")
    ax.barh(labels[::-1], values[::-1], color="#f59e0b")
    ax.set_title("Word Frequency", color="#1e293b")
    ax.tick_params(colors="#475569")
    ax.set_facecolor("#f8fafc")
    fig.tight_layout()
    fig.savefig(output, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    return str(output)


def generate_all_charts(result):
    return {
        "pie": create_pie_chart(result["average_similarity"]),
        "bar": create_bar_chart(result["comparisons"]),
        "frequency": create_word_frequency_chart(result["word_frequency"]),
    }


def generate_pdf_report(result, output_path=None):
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table
    except ImportError as error:
        raise ImportError("reportlab is required to generate PDF reports.") from error

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = Path(output_path or REPORTS_DIR / f"plagiarism_report_{timestamp}.pdf")
    charts = generate_all_charts(result)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(APP_TITLE, styles["Title"]),
        Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles["Normal"]),
        Spacer(1, 12),
        Paragraph(f"Average Similarity: {result['average_similarity']}%", styles["Heading2"]),
    ]

    stats_rows = [["Document", "Words", "Characters", "Sentences", "Paragraphs", "Unique Words"]]
    for document in result["documents"]:
        stats = document["stats"]
        stats_rows.append(
            [
                document["name"],
                stats["word_count"],
                stats["character_count"],
                stats["sentence_count"],
                stats["paragraph_count"],
                stats["unique_word_count"],
            ]
        )
    story.extend([Table(stats_rows), Spacer(1, 12), Paragraph("Comparison Results", styles["Heading2"])])

    for comparison in result["comparisons"]:
        story.append(
            Paragraph(
                f"{comparison['left_name']} vs {comparison['right_name']}: "
                f"{comparison['similarity']}% similarity, {comparison['plagiarism']}% plagiarism",
                styles["Normal"],
            )
        )
        for match in comparison["sentence_matches"][:10]:
            story.append(Paragraph(f"Matched sentence: {match['a']}", styles["BodyText"]))

    story.extend([Spacer(1, 12), Paragraph("Charts", styles["Heading2"])])
    for chart_path in charts.values():
        story.extend([Image(chart_path, width=360, height=220), Spacer(1, 8)])

    SimpleDocTemplate(str(output), pagesize=letter).build(story)
    return str(output)


# -----------------------------
# CustomTkinter desktop interface
# -----------------------------
class PlagiarismApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._theme_name = "dark"
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title(APP_TITLE)
        self.geometry("1420x820")
        self.minsize(1280, 700)

        self.FONT = "Segoe UI"
        self.color_unique = "#22c55e"
        self.color_plagiarized = "#f87171"
        self.color_partial = "#fb923c"
        self.uploaded_file_doc = None
        self._apply_theme("dark")

        self.documents = []
        self.document_a = None
        self.document_b = None
        self.manual_text_a_widget = None
        self.manual_text_b_widget = None
        self.current_result = None
        self.current_charts = {}
        self.compare_mode_var = tk.BooleanVar(value=False)
        self.nav_buttons = {}
        self._scan_anim_id = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)

        self.build_topbar()
        self.build_sidebar()
        self.container = ctk.CTkFrame(self, fg_color=self.panel_bg, corner_radius=0)
        self.container.grid(row=1, column=1, sticky="nsew")
        self.container.grid_columnconfigure(0, weight=1)
        self.container.grid_rowconfigure(0, weight=1)
        self._build_statusbar()

        self.show_dashboard()

    def _apply_theme(self, name):
        t = THEMES[name]
        self._theme_name = name
        self.sidebar_bg = t["sidebar_bg"]
        self.panel_bg = t["panel_bg"]
        self.card_bg = t["card_bg"]
        self.accent = t["accent"]
        self.muted_text = t["muted_text"]
        self.title_text = t["title_text"]
        self.button_bg = t["button_bg"]
        self.hover_bg = t["hover_bg"]
        self._topbar_bg = t["topbar_bg"]
        self._topbar_fg = t["topbar_fg"]
        self._status_bg = t["status_bg"]
        self._status_fg = t["status_fg"]
        self.input_bg = t.get("input_bg", t["card_bg"])
        self.input_fg = t.get("input_fg", t["title_text"])
        self.configure(fg_color=self.panel_bg)

    def _toggle_theme(self):
        pass  # single dark theme only

    def _build_statusbar(self):
        self._statusbar = ctk.CTkFrame(self, height=26, corner_radius=0, fg_color=self._status_bg)
        self._statusbar.grid(row=2, column=0, columnspan=2, sticky="ew")
        self._statusbar.grid_propagate(False)
        self._status_lbl = ctk.CTkLabel(
            self._statusbar, text="Ready",
            font=ctk.CTkFont(family=self.FONT, size=10),
            text_color=self._status_fg)
        self._status_lbl.pack(side="left", padx=12)
        self._clock_lbl = ctk.CTkLabel(
            self._statusbar, text="",
            font=ctk.CTkFont(family=self.FONT, size=10),
            text_color=self._status_fg)
        self._clock_lbl.pack(side="right", padx=12)
        self._tick_clock()

    def _tick_clock(self):
        now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        if hasattr(self, "_clock_lbl") and self._clock_lbl.winfo_exists():
            self._clock_lbl.configure(text=now)
        self.after(1000, self._tick_clock)

    def _set_status(self, msg):
        if hasattr(self, "_status_lbl") and self._status_lbl.winfo_exists():
            self._status_lbl.configure(text=msg)

    def build_topbar(self):
        topbar = ctk.CTkFrame(self, height=62, corner_radius=0, fg_color=self._topbar_bg)
        topbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        topbar.grid_propagate(False)
        topbar.grid_columnconfigure(1, weight=1)
        self._topbar = topbar

        brand = ctk.CTkFrame(topbar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=18, pady=10)
        ctk.CTkLabel(brand, text="⬡", font=ctk.CTkFont(size=26), text_color=self.accent).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(brand, text="PlagiarismIQ",
                     font=ctk.CTkFont(family=self.FONT, size=16, weight="bold"),
                     text_color=self._topbar_fg).pack(side="left")
        ctk.CTkLabel(brand, text=" — Document Checker",
                     font=ctk.CTkFont(family=self.FONT, size=12),
                     text_color=self.muted_text).pack(side="left")

        nav = ctk.CTkFrame(topbar, fg_color="transparent")
        nav.grid(row=0, column=1, sticky="e", padx=16)
        for label, cmd in (("🏠  Dashboard", self.show_dashboard), ("🕐  History", self.show_history)):
            ctk.CTkButton(nav, text=label, command=cmd, fg_color="transparent",
                          hover_color=self.card_bg, text_color=self.muted_text,
                          font=ctk.CTkFont(family=self.FONT, size=12),
                          height=34, corner_radius=6, width=120).pack(side="left", padx=2)
        ctk.CTkButton(nav, text="👤  Account  ▾", fg_color=self.card_bg,
                      hover_color="#2d2d4e",
                      text_color=self._topbar_fg,
                      font=ctk.CTkFont(family=self.FONT, size=12),
                      height=34, corner_radius=8).pack(side="left", padx=(10, 0))

    def build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color=self.sidebar_bg)
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        self._sidebar = sidebar

        # sidebar header
        sidebar_hdr = ctk.CTkFrame(sidebar, fg_color=self.card_bg, corner_radius=0, height=48)
        sidebar_hdr.pack(fill="x")
        sidebar_hdr.pack_propagate(False)
        ctk.CTkLabel(sidebar_hdr, text="NAVIGATION",
                     font=ctk.CTkFont(family=self.FONT, size=9, weight="bold"),
                     text_color=self.muted_text).pack(anchor="w", padx=16, pady=16)

        nav_items = [
            ("📄  Check Document", self.show_dashboard,         True),
            ("🔀  Compare View",   self.show_comparison_view,   False),
            ("🕐  History",        self.show_history,            False),
            ("📊  Reports",        self.show_results,            False),
            ("⚙️  Settings",       lambda: messagebox.showinfo("Settings", "Coming soon."), False),
        ]
        for name, cmd, active in nav_items:
            btn = ctk.CTkButton(
                sidebar, text=name, command=cmd,
                height=44, anchor="w", corner_radius=10,
                fg_color=self.accent if active else "transparent",
                hover_color=self.card_bg,
                font=ctk.CTkFont(family=self.FONT, size=13, weight="bold" if active else "normal"),
                text_color=self.title_text if active else self.muted_text,
            )
            btn.pack(fill="x", padx=12, pady=(10 if active else 3, 3))
            self.nav_buttons[name] = btn

        # sidebar footer divider
        ctk.CTkFrame(sidebar, fg_color=self.card_bg, height=1).pack(fill="x", side="bottom", pady=(0, 40))
        ctk.CTkLabel(sidebar, text="v2.0  •  PlagiarismIQ",
                     font=ctk.CTkFont(family=self.FONT, size=9),
                     text_color=self.muted_text).pack(side="bottom", pady=(0, 8))

    def set_active_nav(self, name):
        for label, button in self.nav_buttons.items():
            is_active = name in label
            button.configure(
                fg_color=self.accent if is_active else "transparent",
                hover_color=self.card_bg,
                text_color=self.title_text if is_active else self.muted_text,
                font=ctk.CTkFont(family=self.FONT, size=13, weight="bold" if is_active else "normal"),
            )

    def clear_container(self):
        for widget in self.container.winfo_children():
            widget.destroy()

    def page_header(self, title, subtitle):
        pass  # top bar handles branding; individual pages have their own headers

    def show_dashboard(self):
        self.set_active_nav("Check Document")
        self.clear_container()

        outer = ctk.CTkFrame(self.container, fg_color=self.panel_bg)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=2)
        outer.grid_columnconfigure(1, weight=3)
        outer.grid_rowconfigure(0, weight=1)

        # ── LEFT PANEL ──────────────────────────────────────────────
        left = ctk.CTkScrollableFrame(outer, fg_color=self.panel_bg, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=14)
        left.grid_columnconfigure(0, weight=1)

        upload_card = ctk.CTkFrame(left, fg_color=self.card_bg, corner_radius=16,
                                     border_width=1, border_color="#2d2d4e")
        upload_card.pack(fill="x", pady=(0, 12))
        # card header stripe
        hdr_strip = ctk.CTkFrame(upload_card, fg_color=self.accent, height=4, corner_radius=0)
        hdr_strip.pack(fill="x")
        ctk.CTkLabel(upload_card, text="📂  Check Your Document",
                     font=ctk.CTkFont(family=self.FONT, size=15, weight="bold"),
                     text_color=self.title_text).pack(anchor="w", padx=18, pady=(14, 10))

        drop_zone = ctk.CTkFrame(upload_card, fg_color=self.input_bg, corner_radius=12,
                                  border_width=2, border_color=self.accent)
        drop_zone.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkLabel(drop_zone, text="📄", font=ctk.CTkFont(size=36), text_color=self.accent).pack(pady=(20, 4))
        ctk.CTkLabel(drop_zone, text="Drag & drop your file here",
                     font=ctk.CTkFont(family=self.FONT, size=13, weight="bold"),
                     text_color=self.title_text).pack()
        ctk.CTkLabel(drop_zone, text="— or —", font=ctk.CTkFont(family=self.FONT, size=11),
                     text_color=self.muted_text).pack(pady=4)
        ctk.CTkButton(drop_zone, text="  Browse File", command=self._dashboard_choose_file,
                      fg_color=self.button_bg, hover_color=self.hover_bg, text_color="#ffffff",
                      corner_radius=10, height=38, width=170,
                      font=ctk.CTkFont(family=self.FONT, size=13, weight="bold")).pack(pady=(0, 8))
        ctk.CTkLabel(drop_zone, text="Supported: .docx  .pdf  .txt   •   Max 25 MB",
                     font=ctk.CTkFont(family=self.FONT, size=10),
                     text_color=self.muted_text).pack(pady=(0, 16))

        file_row = ctk.CTkFrame(upload_card, fg_color=self.input_bg, corner_radius=8)
        file_row.pack(fill="x", padx=18, pady=(0, 10))
        self._dash_file_label = ctk.CTkLabel(file_row, text="No file selected",
                                              font=ctk.CTkFont(family=self.FONT, size=11),
                                              text_color=self.muted_text)
        self._dash_file_label.pack(side="left", padx=12, pady=8)

        ctk.CTkButton(upload_card, text="🔍  Run Similarity Check",
                      command=self._dashboard_run_check,
                      fg_color=self.button_bg, hover_color=self.hover_bg, text_color="#ffffff",
                      corner_radius=10, height=42,
                      font=ctk.CTkFont(family=self.FONT, size=14, weight="bold")).pack(fill="x", padx=18, pady=(0, 8))
        ctk.CTkLabel(upload_card, text="🔒  End-to-end encrypted  •  Files never stored",
                     font=ctk.CTkFont(family=self.FONT, size=10), text_color=self.muted_text).pack(pady=(0, 12))

        preview_card = ctk.CTkFrame(left, fg_color=self.card_bg, corner_radius=16,
                                     border_width=1, border_color="#2d2d4e")
        preview_card.pack(fill="both", expand=True)
        ph = ctk.CTkFrame(preview_card, fg_color="transparent")
        ph.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(ph, text="📝  Document Preview",
                     font=ctk.CTkFont(family=self.FONT, size=13, weight="bold"),
                     text_color=self.title_text).pack(side="left")
        ctk.CTkLabel(ph, text="(First 200 words)",
                     font=ctk.CTkFont(family=self.FONT, size=10), text_color=self.muted_text).pack(side="right")
        self._dash_preview_text = tk.Text(
            preview_card, wrap="word", bg=self.input_bg, fg=self.input_fg,
            relief="flat", padx=12, pady=10, font=(self.FONT, 11), height=7,
            state="disabled", insertbackground=self.accent)
        self._dash_preview_text.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        # ── RIGHT PANEL ─────────────────────────────────────────────
        right = ctk.CTkScrollableFrame(outer, fg_color=self.panel_bg, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=14)
        right.grid_columnconfigure(0, weight=1)

        res_hdr = ctk.CTkFrame(right, fg_color="transparent")
        res_hdr.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(res_hdr, text="📊  Similarity Results",
                     font=ctk.CTkFont(family=self.FONT, size=18, weight="bold"),
                     text_color=self.title_text).pack(side="left")
        ctk.CTkButton(res_hdr, text="⬇  Download", command=self.export_report,
                      fg_color=self.card_bg, hover_color=self.button_bg, text_color=self.muted_text,
                      corner_radius=8, height=32, border_width=1, border_color="#2d2d4e",
                      font=ctk.CTkFont(family=self.FONT, size=11)).pack(side="right", padx=(6, 0))
        ctk.CTkButton(res_hdr, text="↗  Share", command=self.copy_summary_to_clipboard,
                      fg_color=self.card_bg, hover_color=self.button_bg, text_color=self.muted_text,
                      corner_radius=8, height=32, border_width=1, border_color="#2d2d4e",
                      font=ctk.CTkFont(family=self.FONT, size=11)).pack(side="right")

        sim_card = ctk.CTkFrame(right, fg_color=self.card_bg, corner_radius=16,
                                  border_width=1, border_color="#2d2d4e")
        sim_card.pack(fill="x", pady=(0, 12))
        ctk.CTkFrame(sim_card, fg_color=self.accent, height=4, corner_radius=0).pack(fill="x")
        sim_inner = ctk.CTkFrame(sim_card, fg_color="transparent")
        sim_inner.pack(fill="x", padx=18, pady=16)
        sim_inner.grid_columnconfigure(1, weight=1)

        similarity_val = self.current_result["average_similarity"] if self.current_result else 0
        unique_val = max(0, 100 - similarity_val)

        canvas_size = 155
        donut = tk.Canvas(sim_inner, width=canvas_size, height=canvas_size,
                          bg=self.card_bg, highlightthickness=0)
        donut.grid(row=0, column=0, rowspan=4, padx=(0, 20))
        self._draw_donut(donut, similarity_val, canvas_size)

        stats_f = ctk.CTkFrame(sim_inner, fg_color="transparent")
        stats_f.grid(row=0, column=1, sticky="nsew")
        msg = ("⚠️  Moderate similarity detected.\nSimilar content found in other sources."
               if similarity_val > 15 else
               "✅  Document appears mostly unique.\nLow similarity detected.")
        ctk.CTkLabel(stats_f, text=msg, font=ctk.CTkFont(family=self.FONT, size=12),
                     text_color=self.muted_text, justify="left", wraplength=250).pack(anchor="w", pady=(0, 12))
        for lbl, val, col in [
            ("Matched Content", f"{similarity_val}%", self.color_plagiarized),
            ("Unique Content",  f"{unique_val}%",    self.color_unique),
            ("Excluded",        "0%",               self.color_partial),
        ]:
            rf = ctk.CTkFrame(stats_f, fg_color=self.input_bg, corner_radius=8)
            rf.pack(fill="x", anchor="w", pady=3)
            ctk.CTkLabel(rf, text=val, font=ctk.CTkFont(family=self.FONT, size=18, weight="bold"),
                         text_color=col, width=72, anchor="w").pack(side="left", padx=(10, 0), pady=6)
            ctk.CTkLabel(rf, text=lbl, font=ctk.CTkFont(family=self.FONT, size=12),
                         text_color=self.title_text).pack(side="left", padx=4)

        sources_card = ctk.CTkFrame(right, fg_color=self.card_bg, corner_radius=16,
                                      border_width=1, border_color="#2d2d4e")
        sources_card.pack(fill="x", pady=(0, 12))
        ctk.CTkFrame(sources_card, fg_color="#f87171", height=4, corner_radius=0).pack(fill="x")
        sh = ctk.CTkFrame(sources_card, fg_color="transparent")
        sh.pack(fill="x", padx=18, pady=(14, 6))
        ctk.CTkLabel(sh, text="🔍  Matched Sources",
                     font=ctk.CTkFont(family=self.FONT, size=14, weight="bold"),
                     text_color=self.title_text).pack(side="left")
        ctk.CTkLabel(sh, text="Score",
                     font=ctk.CTkFont(family=self.FONT, size=11), text_color=self.muted_text).pack(side="right")

        sources = self._get_dashboard_sources()
        badge_colors = ["#f87171", "#fb923c", "#fbbf24", "#34d399"]
        if not sources:
            ctk.CTkLabel(sources_card, text="Run a check to see matched sources here.",
                         font=ctk.CTkFont(family=self.FONT, size=12), text_color=self.muted_text).pack(
                anchor="w", padx=18, pady=(0, 14))
        for i, (name, url, pct) in enumerate(sources[:4]):
            sep = ctk.CTkFrame(sources_card, fg_color="#2d2d4e", height=1)
            sep.pack(fill="x", padx=18)
            row = ctk.CTkFrame(sources_card, fg_color=self.input_bg, corner_radius=8)
            row.pack(fill="x", padx=18, pady=5)
            bc = badge_colors[i % len(badge_colors)]
            badge = ctk.CTkFrame(row, fg_color=bc, corner_radius=8, width=30, height=30)
            badge.pack(side="left", padx=(10, 12), pady=8)
            badge.pack_propagate(False)
            ctk.CTkLabel(badge, text=str(i + 1),
                         font=ctk.CTkFont(family=self.FONT, size=11, weight="bold"),
                         text_color="#0d0d1a").pack(expand=True)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, pady=6)
            ctk.CTkLabel(info, text=name,
                         font=ctk.CTkFont(family=self.FONT, size=12, weight="bold"),
                         text_color=self.title_text, anchor="w").pack(anchor="w")
            ctk.CTkLabel(info, text=url,
                         font=ctk.CTkFont(family=self.FONT, size=10),
                         text_color=self.muted_text, anchor="w").pack(anchor="w")
            ctk.CTkLabel(row, text=f"{pct}%",
                         font=ctk.CTkFont(family=self.FONT, size=14, weight="bold"),
                         text_color=bc).pack(side="right", padx=12)

        ctk.CTkButton(sources_card, text="View All Sources  ▸", command=self.show_results,
                      fg_color="transparent", hover_color=self.input_bg, text_color=self.accent,
                      font=ctk.CTkFont(family=self.FONT, size=12, weight="bold"), height=38).pack(
            fill="x", padx=18, pady=(4, 12))

    def _draw_donut(self, canvas, pct, size):
        import math
        canvas.delete("all")
        canvas.configure(bg=self.card_bg)
        cx, cy, r, w = size // 2, size // 2, size // 2 - 18, 22
        # track ring
        canvas.create_oval(cx-r, cy-r, cx+r, cy+r, outline="#2d2d4e", width=w)
        # glow ring fill
        if pct > 0:
            steps = max(1, int(3.6 * min(pct, 100)))
            for i in range(steps):
                a1 = math.radians(90 - i * 360 / 100)
                a2 = math.radians(90 - (i + 1) * 360 / 100)
                x1 = cx + r * math.cos(a1); y1 = cy - r * math.sin(a1)
                x2 = cx + r * math.cos(a2); y2 = cy - r * math.sin(a2)
                canvas.create_line(x1, y1, x2, y2, fill=self.color_plagiarized, width=w, capstyle="round")
        canvas.create_text(cx, cy - 10, text=f"{pct}%",
                           font=(self.FONT, 20, "bold"), fill=self.color_plagiarized)
        canvas.create_text(cx, cy + 12, text="Similarity",
                           font=(self.FONT, 10), fill=self.title_text)
        canvas.create_text(cx, cy + 28, text="Overall Score",
                           font=(self.FONT, 8), fill=self.muted_text)

    def _get_dashboard_sources(self):
        if not self.current_result:
            return []
        out = []
        for comp in self.current_result.get("comparisons", []):
            if comp.get("source") and comp["similarity"] > 0:
                out.append((comp["source"], comp["source"], comp["similarity"]))
        return sorted(out, key=lambda x: x[2], reverse=True)

    def _dashboard_choose_file(self):
        path = filedialog.askopenfilename(
            title="Select document",
            filetypes=[("Supported files", "*.txt *.pdf *.docx"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            doc = load_document(path)
        except (ValueError, ImportError, OSError) as e:
            messagebox.showwarning("File error", str(e))
            return
        self.uploaded_file_doc = doc
        self.document_a = {**doc, "source": doc["name"]}
        self._dash_file_label.configure(
            text=f"📄  {doc['name']}  ({doc['size']})", text_color=self.title_text)
        preview = " ".join(doc["text"].split()[:200])
        self._dash_preview_text.configure(state="normal")
        self._dash_preview_text.delete("1.0", "end")
        self._dash_preview_text.insert("1.0", preview + ("..." if len(doc["text"].split()) > 200 else ""))
        self._dash_preview_text.configure(state="disabled")

    def _dashboard_run_check(self):
        if not self.document_a:
            messagebox.showinfo("No file", "Please choose a file first.")
            return
        self.run_comparison(show_message=False)
        self.show_dashboard()

    def metric_card(self, parent, title, value, row, column):
        card = ctk.CTkFrame(parent, fg_color=self.card_bg, corner_radius=8)
        card.grid(row=row, column=column, sticky="ew", padx=6, pady=6)
        ctk.CTkLabel(card, text=value, font=ctk.CTkFont(family=self.FONT, size=26, weight="bold"), text_color=self.accent).pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(card, text=title, text_color=self.title_text, font=ctk.CTkFont(family=self.FONT, size=11, weight="bold")).pack(anchor="w", padx=14, pady=(0, 12))

    def show_upload(self):
        self.set_active_nav("Upload Files")
        self.clear_container()
        self.page_header("Plagiarism & Similarity Checker", "Submit text or files to analyze for plagiarism and similarity. Use the input pane and upload options to start.")

        body = ctk.CTkFrame(self.container, fg_color=self.panel_bg)
        body.grid(row=1, column=0, sticky="nsew", padx=26, pady=(0, 24))
        body.grid_columnconfigure((0, 1), weight=1)
        body.grid_rowconfigure(1, weight=1)

        actions = ctk.CTkFrame(body, fg_color=self.panel_bg)
        actions.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        ctk.CTkButton(actions, text="Analyze Content", command=self.run_comparison, height=40, fg_color=self.accent, text_color="#ffffff", corner_radius=14, font=ctk.CTkFont(family=self.FONT, size=12, weight="bold")).pack(side="left", padx=(0, 10))
        ctk.CTkButton(actions, text="Clear All", command=self.clear_all_documents, height=40, fg_color=self.button_bg, text_color="#ffffff", corner_radius=14, font=ctk.CTkFont(family=self.FONT, size=12, weight="bold")).pack(side="left")
        ctk.CTkCheckBox(actions, text="Compare Two Documents", variable=self.compare_mode_var, onvalue=True, offvalue=False, text_color=self.title_text, font=ctk.CTkFont(family=self.FONT, size=12), corner_radius=10).pack(side="left", padx=(16, 0))

        manual_frame = ctk.CTkFrame(body, fg_color=self.card_bg, corner_radius=16)
        manual_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 12), pady=0)
        manual_frame.grid_rowconfigure(3, weight=1)
        manual_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(manual_frame, text="Primary Document", font=ctk.CTkFont(family=self.FONT, size=18, weight="bold"), text_color=self.title_text).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 8))
        ctk.CTkLabel(manual_frame, text="Enter or paste the document to analyze. By default this is checked against internal and online sources.", text_color=self.muted_text, font=ctk.CTkFont(family=self.FONT, size=12), wraplength=420, justify="left").grid(row=1, column=0, sticky="w", padx=18, pady=(0, 2))

        self.wc_label_a = ctk.CTkLabel(manual_frame, text="Words: 0", text_color=self.muted_text, font=ctk.CTkFont(family=self.FONT, size=11))
        self.wc_label_a.grid(row=2, column=0, sticky="e", padx=18, pady=(0, 2))

        self.manual_text_a_widget = tk.Text(manual_frame, wrap="word", bg=self.input_bg, fg=self.input_fg, insertbackground=self.accent, relief="flat", padx=12, pady=12, font=(self.FONT, 12), selectbackground=self.accent)
        self.manual_text_a_widget.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 12))
        self.manual_text_a_widget.bind("<KeyRelease>", lambda e: self._update_word_count(self.manual_text_a_widget, self.wc_label_a))

        control_frame = ctk.CTkFrame(manual_frame, fg_color=self.card_bg)
        control_frame.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 18))
        ctk.CTkButton(control_frame, text="Upload Primary File", command=self.load_file_a, fg_color=self.button_bg, text_color="#ffffff", corner_radius=14, font=ctk.CTkFont(family=self.FONT, size=12)).pack(side="left", padx=(0, 10), pady=8)
        ctk.CTkButton(control_frame, text="Clear Primary Text", command=self.clear_manual_text_a, fg_color=self.button_bg, text_color="#ffffff", corner_radius=14, font=ctk.CTkFont(family=self.FONT, size=12)).pack(side="left", padx=(0, 10), pady=8)

        file_panel = ctk.CTkFrame(body, fg_color=self.card_bg, corner_radius=16)
        file_panel.grid(row=1, column=1, sticky="nsew", padx=(12, 0), pady=0)
        file_panel.grid_rowconfigure(3, weight=1)
        file_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(file_panel, text="Optional Secondary Document", font=ctk.CTkFont(family=self.FONT, size=18, weight="bold"), text_color=self.title_text).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 8))
        ctk.CTkLabel(file_panel, text="Upload or paste a second document only when Compare mode is enabled.", text_color=self.muted_text, font=ctk.CTkFont(family=self.FONT, size=12), wraplength=420, justify="left").grid(row=1, column=0, sticky="w", padx=18, pady=(0, 2))

        self.wc_label_b = ctk.CTkLabel(file_panel, text="Words: 0", text_color=self.muted_text, font=ctk.CTkFont(family=self.FONT, size=11))
        self.wc_label_b.grid(row=2, column=0, sticky="e", padx=18, pady=(0, 2))

        self.manual_text_b_widget = tk.Text(file_panel, wrap="word", bg=self.input_bg, fg=self.input_fg, insertbackground=self.accent, relief="flat", padx=12, pady=12, font=(self.FONT, 12), selectbackground=self.accent)
        self.manual_text_b_widget.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 12))
        self.manual_text_b_widget.bind("<KeyRelease>", lambda e: self._update_word_count(self.manual_text_b_widget, self.wc_label_b))

        b_control_frame = ctk.CTkFrame(file_panel, fg_color=self.card_bg)
        b_control_frame.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 12))
        ctk.CTkButton(b_control_frame, text="Upload Secondary File", command=self.load_file_b, fg_color=self.button_bg, text_color="#ffffff", corner_radius=14, font=ctk.CTkFont(family=self.FONT, size=12)).pack(side="left", padx=(0, 10), pady=8)
        ctk.CTkButton(b_control_frame, text="Clear Secondary Text", command=self.clear_manual_text_b, fg_color=self.button_bg, text_color="#ffffff", corner_radius=14, font=ctk.CTkFont(family=self.FONT, size=12)).pack(side="left", pady=8)

        scan_settings = ctk.CTkFrame(file_panel, fg_color=self.panel_bg, corner_radius=14)
        scan_settings.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 12))
        ctk.CTkLabel(scan_settings, text="Scan Settings", font=ctk.CTkFont(family=self.FONT, size=14, weight="bold"), text_color=self.title_text).pack(anchor="w", padx=14, pady=(14, 8))
        ctk.CTkLabel(scan_settings, text="• Similarity and plagiarism are analyzed together.", text_color=self.muted_text, font=ctk.CTkFont(family=self.FONT, size=12)).pack(anchor="w", padx=14, pady=(0, 4))
        ctk.CTkLabel(scan_settings, text="• Source references are generated from matching documents.", text_color=self.muted_text, font=ctk.CTkFont(family=self.FONT, size=12)).pack(anchor="w", padx=14, pady=(0, 14))

        self.file_list = ctk.CTkScrollableFrame(file_panel, fg_color=self.card_bg)
        self.file_list.grid(row=6, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self.file_list.grid_rowconfigure(0, weight=1)
        self.refresh_file_list()

    def add_documents(self):
        paths = filedialog.askopenfilenames(
            title="Select documents",
            filetypes=[("Supported files", "*.txt *.pdf *.docx"), ("All files", "*.*")],
        )
        if not paths:
            return

        errors = []
        known_fingerprints = {item["fingerprint"] for item in self.documents}
        for path in paths:
            try:
                document = load_document(path)
            except (ValueError, ImportError, OSError) as error:
                errors.append(f"{path}: {error}")
                continue
            if document["fingerprint"] not in known_fingerprints:
                self.documents.append(document)
                known_fingerprints.add(document["fingerprint"])

        if errors:
            messagebox.showwarning("Some files could not be loaded", "\n".join(errors[:5]))

        self.refresh_file_list()
        if len(self.documents) >= 2:
            self.run_comparison(show_message=False)

    def clear_documents(self):
        self.documents = []
        self.current_result = None
        self.current_charts = {}
        self.refresh_file_list()

    def load_file_a(self):
        path = filedialog.askopenfilename(
            title="Select input text file",
            filetypes=[("Supported files", "*.txt *.pdf *.docx"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            document = load_document(path)
        except (ValueError, ImportError, OSError) as error:
            messagebox.showwarning("File could not be loaded", str(error))
            return
        self.document_a = {
            "path": document["path"],
            "name": document["name"],
            "extension": document["extension"],
            "size_bytes": document["size_bytes"],
            "size": document["size"],
            "text": document["text"],
            "stats": document["stats"],
            "fingerprint": document["fingerprint"],
            "source": document["name"],
        }
        if self.manual_text_a_widget and self.manual_text_a_widget.winfo_exists():
            self.manual_text_a_widget.delete("1.0", "end")
            self.manual_text_a_widget.insert("1.0", document["text"])

    def load_file_b(self):
        path = filedialog.askopenfilename(
            title="Select comparison file",
            filetypes=[("Supported files", "*.txt *.pdf *.docx"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            document = load_document(path)
        except (ValueError, ImportError, OSError) as error:
            messagebox.showwarning("File could not be loaded", str(error))
            return
        self.document_b = {
            "path": document["path"],
            "name": document["name"],
            "extension": document["extension"],
            "size_bytes": document["size_bytes"],
            "size": document["size"],
            "text": document["text"],
            "stats": document["stats"],
            "fingerprint": document["fingerprint"],
            "source": document["name"],
        }
        if self.manual_text_b_widget and self.manual_text_b_widget.winfo_exists():
            self.manual_text_b_widget.delete("1.0", "end")
            self.manual_text_b_widget.insert("1.0", document["text"])

    def _update_word_count(self, widget, label):
        text = widget.get("1.0", "end").strip()
        count = len(WORD_RE.findall(text))
        label.configure(text=f"Words: {count}")

    def refresh_file_list(self):
        if not hasattr(self, "file_list") or not self.file_list.winfo_exists():
            return
        for widget in self.file_list.winfo_children():
            widget.destroy()

        if not self.documents:
            ctk.CTkLabel(self.file_list, text="No documents selected yet.", text_color=self.muted_text, font=ctk.CTkFont(family=self.FONT, size=12)).pack(anchor="w", padx=18, pady=18)
            return

        for document in self.documents:
            stats = document["stats"]
            card = ctk.CTkFrame(self.file_list, fg_color=self.card_bg, corner_radius=8)
            card.pack(fill="x", padx=14, pady=8)
            ctk.CTkLabel(card, text=document["name"], font=ctk.CTkFont(family=self.FONT, size=16, weight="bold"), text_color=self.title_text).pack(anchor="w", padx=14, pady=(12, 2))
            details = (
                f"{document['size']} | {stats['word_count']} words | {stats['sentence_count']} sentences | "
                f"{stats['paragraph_count']} paragraphs | {stats['unique_word_count']} unique words"
            )
            ctk.CTkLabel(card, text=details, text_color=self.muted_text, font=ctk.CTkFont(family=self.FONT, size=11)).pack(anchor="w", padx=14, pady=(0, 4))
            ctk.CTkLabel(card, text=f"SHA-256: {document['fingerprint']}", text_color="#6f8799", font=ctk.CTkFont(family=self.FONT, size=11)).pack(anchor="w", padx=14, pady=(0, 12))

    def get_manual_text(self, widget):
        if not widget or not widget.winfo_exists():
            return ""
        return widget.get("1.0", "end").strip()

    def update_manual_document_a(self):
        text = self.get_manual_text(self.manual_text_a_widget)
        if text:
            self.document_a = create_manual_document(text, name="Input Text", source="Manual Input")
        else:
            self.document_a = None

    def update_manual_document_b(self):
        text = self.get_manual_text(self.manual_text_b_widget)
        if text:
            self.document_b = create_manual_document(text, name="Comparison Text", source="Manual Comparison")
        else:
            self.document_b = None

    def clear_manual_text_a(self):
        if self.manual_text_a_widget and self.manual_text_a_widget.winfo_exists():
            self.manual_text_a_widget.delete("1.0", "end")
        self.document_a = None

    def clear_manual_text_b(self):
        if self.manual_text_b_widget and self.manual_text_b_widget.winfo_exists():
            self.manual_text_b_widget.delete("1.0", "end")
        self.document_b = None

    def clear_all_documents(self):
        self.clear_manual_text_a()
        self.clear_manual_text_b()
        self.documents = []
        self.current_result = None
        self.current_charts = {}

    def run_comparison(self, show_message=True):
        # Only read manual text widgets if they currently exist
        if self.manual_text_a_widget and self.manual_text_a_widget.winfo_exists():
            self.update_manual_document_a()
        if self.manual_text_b_widget and self.manual_text_b_widget.winfo_exists():
            self.update_manual_document_b()

        documents = []
        if self.document_a:
            documents.append(self.document_a)
        if self.document_b:
            documents.append(self.document_b)

        compare_mode = self.compare_mode_var.get()
        if compare_mode:
            if len(documents) < 2:
                if show_message:
                    messagebox.showinfo("Need more content", "Compare mode is enabled. Please provide two documents or text entries.")
                return
            self.current_result = compare_documents(documents)
        else:
            document = documents[0] if documents else None
            if not document:
                if show_message:
                    messagebox.showinfo("Need content", "Please provide a document to analyze for plagiarism and similarity.")
                return
            self.current_result = analyze_single_document(document)
        try:
            self.current_charts = generate_all_charts(self.current_result)
            add_history_record(self.current_result)
        except ImportError as error:
            messagebox.showerror("Missing dependency", str(error))
            return
        except Exception as error:
            messagebox.showerror("Comparison failed", str(error))
            return
        if show_message:
            self.show_results()

    def run_similarity_check(self):
        self.run_comparison()

    def run_plagiarism_check(self):
        self.run_comparison()

    def show_results(self):
        self.set_active_nav("Reports")
        self.clear_container()

        body = ctk.CTkScrollableFrame(self.container, fg_color=self.panel_bg)
        body.pack(fill="both", expand=True, padx=24, pady=18)
        body.grid_columnconfigure(0, weight=1)

        if not self.current_result:
            ctk.CTkLabel(body, text="Upload documents or enter manual text, then click Analyze Content to generate results.",
                         text_color=self.muted_text, font=ctk.CTkFont(family=self.FONT, size=14),
                         wraplength=700, justify="left").pack(anchor="w", pady=20)
            return

        avg_plagiarism = self.average_plagiarism()
        avg_unique = max(0, 100 - self.current_result["average_similarity"])
        exact_match_pct = self.calculate_exact_match_percentage()
        partial_match_pct = self.calculate_partial_match_percentage()
        is_unique = avg_plagiarism < 20

        summary_frame = ctk.CTkFrame(body, fg_color=self.card_bg, corner_radius=18,
                                       border_width=1, border_color="#2d2d4e")
        summary_frame.pack(fill="x", pady=(0, 20))
        summary_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        indicator_text = "✅  Content is Mostly Unique" if is_unique else "⚠️  Plagiarism Detected"
        indicator_color = self.color_unique if is_unique else self.color_plagiarized
        indicator_frame = ctk.CTkFrame(summary_frame, fg_color=indicator_color, corner_radius=14)
        indicator_frame.grid(row=0, column=0, columnspan=4, sticky="ew", padx=16, pady=(16, 14))
        ctk.CTkLabel(indicator_frame, text=indicator_text,
                     font=ctk.CTkFont(family=self.FONT, size=19, weight="bold"),
                     text_color="#ffffff").pack(pady=12)

        summary_metrics = [
            ("Plagiarized",     f"{avg_plagiarism}%",  self.color_plagiarized),
            ("Unique Content",  f"{avg_unique}%",       self.color_unique),
            ("Exact Matches",   f"{exact_match_pct}%",  self.color_plagiarized),
            ("Partial Matches", f"{partial_match_pct}%", self.color_partial),
        ]
        for idx, (label, value, color) in enumerate(summary_metrics):
            metric_frame = ctk.CTkFrame(summary_frame, fg_color=self.input_bg, corner_radius=14)
            metric_frame.grid(row=1, column=idx, sticky="ew", padx=8, pady=(0, 16))
            ctk.CTkLabel(metric_frame, text=value,
                         font=ctk.CTkFont(family=self.FONT, size=30, weight="bold"),
                         text_color=color).pack(pady=(14, 4))
            ctk.CTkLabel(metric_frame, text=label,
                         font=ctk.CTkFont(family=self.FONT, size=12),
                         text_color=self.title_text).pack(pady=(0, 14))

        action_frame = ctk.CTkFrame(body, fg_color=self.card_bg, corner_radius=14,
                                      border_width=1, border_color="#2d2d4e")
        action_frame.pack(fill="x", pady=(0, 20))
        btn_cfg = dict(text_color="#ffffff", corner_radius=10, height=42,
                       font=ctk.CTkFont(family=self.FONT, size=12, weight="bold"))
        ctk.CTkButton(action_frame, text="🔀 Compare View", command=self.show_comparison_view,
                      fg_color="#4f46e5", hover_color="#4338ca", **btn_cfg).pack(side="left", padx=(12, 6), pady=10)
        ctk.CTkButton(action_frame, text="🔍 Re-Check", command=self.run_comparison,
                      fg_color=self.button_bg, hover_color=self.hover_bg, **btn_cfg).pack(side="left", padx=(0, 6), pady=10)
        ctk.CTkButton(action_frame, text="✏️ Grammar", command=self.check_grammar,
                      fg_color="#0f766e", hover_color="#0d9488", **btn_cfg).pack(side="left", padx=6, pady=10)
        ctk.CTkButton(action_frame, text="🤖 AI Detect", command=self.detect_ai,
                      fg_color="#6d28d9", hover_color="#7c3aed", **btn_cfg).pack(side="left", padx=6, pady=10)
        ctk.CTkButton(action_frame, text="📄 PDF Report", command=self.export_report,
                      fg_color="#065f46", hover_color="#047857", **btn_cfg).pack(side="left", padx=6, pady=10)
        ctk.CTkButton(action_frame, text="📊 CSV Export", command=self.export_csv,
                      fg_color="#065f46", hover_color="#047857", **btn_cfg).pack(side="left", padx=6, pady=10)
        ctk.CTkButton(action_frame, text="📋 Copy", command=self.copy_summary_to_clipboard,
                      fg_color=self.card_bg, hover_color=self.input_bg, text_color=self.muted_text,
                      corner_radius=10, height=42, border_width=1, border_color="#2d2d4e",
                      font=ctk.CTkFont(family=self.FONT, size=12)).pack(side="left", padx=6, pady=10)

        source_frame = ctk.CTkFrame(body, fg_color=self.card_bg, corner_radius=16,
                                      border_width=1, border_color="#2d2d4e")
        source_frame.pack(fill="x", pady=(0, 20))
        ctk.CTkFrame(source_frame, fg_color=self.color_plagiarized, height=4, corner_radius=0).pack(fill="x")
        ctk.CTkLabel(source_frame, text="📌  Source Breakdown",
                     font=ctk.CTkFont(family=self.FONT, size=18, weight="bold"),
                     text_color=self.title_text).pack(anchor="w", padx=20, pady=(16, 12))
        self.draw_source_breakdown(source_frame)
        ctk.CTkLabel(source_frame, text="", font=ctk.CTkFont(size=1)).pack(pady=8)

        document_preview_frame = ctk.CTkFrame(body, fg_color=self.card_bg, corner_radius=16,
                                               border_width=1, border_color="#2d2d4e")
        document_preview_frame.pack(fill="both", expand=True, pady=(0, 20))
        # Document stats panel
        if self.current_result and self.current_result.get("documents"):
            stats_panel = ctk.CTkFrame(body, fg_color=self.card_bg, corner_radius=16,
                                         border_width=1, border_color="#2d2d4e")
            stats_panel.pack(fill="x", pady=(0, 20))
            ctk.CTkFrame(stats_panel, fg_color=self.accent, height=4, corner_radius=0).pack(fill="x")
            ctk.CTkLabel(stats_panel, text="📈  Document Statistics",
                         font=ctk.CTkFont(family=self.FONT, size=18, weight="bold"),
                         text_color=self.title_text).pack(anchor="w", padx=20, pady=(16, 8))
            stats_inner = ctk.CTkFrame(stats_panel, fg_color=self.input_bg, corner_radius=10)
            stats_inner.pack(fill="x", padx=20, pady=(0, 16))
            for doc in self.current_result["documents"]:
                s = doc["stats"]
                row_frame = ctk.CTkFrame(stats_inner, fg_color=self.card_bg, corner_radius=8)
                row_frame.pack(fill="x", pady=4, padx=4)
                ctk.CTkLabel(row_frame, text=doc["name"],
                             font=ctk.CTkFont(family=self.FONT, size=13, weight="bold"),
                             text_color=self.title_text).pack(side="left", padx=14, pady=10)
                ctk.CTkLabel(row_frame,
                             text=f"Words: {s['word_count']}  |  Sentences: {s['sentence_count']}  |  Paragraphs: {s['paragraph_count']}  |  Unique: {s['unique_word_count']}",
                             font=ctk.CTkFont(family=self.FONT, size=12),
                             text_color=self.muted_text).pack(side="left", padx=8, pady=10)

        ctk.CTkLabel(document_preview_frame, text="📄  Document Preview",
                     font=ctk.CTkFont(family=self.FONT, size=18, weight="bold"),
                     text_color=self.title_text).pack(anchor="w", padx=20, pady=(16, 4))
        legend_frame = ctk.CTkFrame(document_preview_frame, fg_color=self.input_bg, corner_radius=8)
        legend_frame.pack(anchor="w", padx=20, pady=(4, 12))
        for color, label in [(self.color_plagiarized, "Plagiarized"), (self.color_partial, "Paraphrased"), (self.accent, "Unique")]:
            legend_item = ctk.CTkFrame(legend_frame, fg_color=color, corner_radius=6)
            legend_item.pack(side="left", padx=6, pady=6)
            ctk.CTkLabel(legend_item, text=label,
                         text_color="#0d0d1a",
                         font=ctk.CTkFont(family=self.FONT, size=11, weight="bold"),
                         padx=10, pady=5).pack()
        self.draw_document_preview(document_preview_frame)

    def average_plagiarism(self):
        comparisons = self.current_result.get("comparisons", []) if self.current_result else []
        if not comparisons:
            return 0
        return round(sum(item["plagiarism"] for item in comparisons) / len(comparisons), 1)

    def calculate_exact_match_percentage(self):
        if not self.current_result or not self.current_result.get("comparisons"):
            return 0
        total_sentences = max(1, sum(doc["stats"].get("sentence_count", 0) for doc in self.current_result["documents"]))
        exact_matches = sum(len(comp.get("sentence_matches", [])) for comp in self.current_result["comparisons"])
        return safe_percent(exact_matches / total_sentences) if total_sentences > 0 else 0

    def calculate_partial_match_percentage(self):
        if not self.current_result or not self.current_result.get("comparisons"):
            return 0
        total_sentences = max(1, sum(doc["stats"].get("sentence_count", 0) for doc in self.current_result["documents"]))
        partial_matches = sum(len(comp.get("paraphrase_matches", [])) for comp in self.current_result["comparisons"])
        return safe_percent(partial_matches / total_sentences) if total_sentences > 0 else 0

    # ------------------------------------------------------------------
    # Side-by-side comparison view with Comparison Highlights sidebar
    # ------------------------------------------------------------------
    def show_comparison_view(self):
        self.set_active_nav("Compare View")
        self.clear_container()

        # ── outer: 3 columns  [Doc A | Doc B | Highlights sidebar]
        outer = ctk.CTkFrame(self.container, fg_color=self.panel_bg)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=5)
        outer.grid_columnconfigure(1, weight=5)
        outer.grid_columnconfigure(2, weight=4)
        outer.grid_rowconfigure(1, weight=1)

        # ── top toolbar ──────────────────────────────────────────────
        toolbar = ctk.CTkFrame(outer, fg_color=self.card_bg, corner_radius=0,
                               border_width=0, height=52)
        toolbar.grid(row=0, column=0, columnspan=3, sticky="ew")
        toolbar.grid_propagate(False)
        ctk.CTkLabel(toolbar, text="🔀  Side-by-Side Comparison",
                     font=ctk.CTkFont(family=self.FONT, size=15, weight="bold"),
                     text_color=self.title_text).pack(side="left", padx=18, pady=14)

        btn_cfg = dict(corner_radius=8, height=34,
                       font=ctk.CTkFont(family=self.FONT, size=12, weight="bold"))
        ctk.CTkButton(toolbar, text="📂 Load Doc A", command=self._cmp_load_a,
                      fg_color=self.button_bg, hover_color=self.hover_bg,
                      text_color="#ffffff", **btn_cfg).pack(side="left", padx=(0, 6), pady=9)
        ctk.CTkButton(toolbar, text="📂 Load Doc B", command=self._cmp_load_b,
                      fg_color="#0f766e", hover_color="#0d9488",
                      text_color="#ffffff", **btn_cfg).pack(side="left", padx=(0, 6), pady=9)
        ctk.CTkButton(toolbar, text="⚡ Run Compare", command=self._cmp_run,
                      fg_color="#4f46e5", hover_color="#4338ca",
                      text_color="#ffffff", **btn_cfg).pack(side="left", padx=(0, 6), pady=9)
        ctk.CTkButton(toolbar, text="🗑 Clear", command=self._cmp_clear,
                      fg_color=self.card_bg, hover_color=self.input_bg,
                      text_color=self.muted_text, border_width=1,
                      border_color="#2d2d4e", **btn_cfg).pack(side="left", pady=9)

        # live similarity badge (updated after run)
        self._cmp_badge_var = tk.StringVar(value="—")
        badge_frame = ctk.CTkFrame(toolbar, fg_color=self.input_bg, corner_radius=8)
        badge_frame.pack(side="right", padx=18, pady=9)
        ctk.CTkLabel(badge_frame, text="Similarity:",
                     font=ctk.CTkFont(family=self.FONT, size=11),
                     text_color=self.muted_text).pack(side="left", padx=(10, 4))
        self._cmp_badge_lbl = ctk.CTkLabel(badge_frame, textvariable=self._cmp_badge_var,
                                            font=ctk.CTkFont(family=self.FONT, size=14, weight="bold"),
                                            text_color=self.color_plagiarized)
        self._cmp_badge_lbl.pack(side="left", padx=(0, 10))

        # ── Document A pane ─────────────────────────────────────────
        pane_a = ctk.CTkFrame(outer, fg_color=self.card_bg, corner_radius=0,
                               border_width=1, border_color="#2d2d4e")
        pane_a.grid(row=1, column=0, sticky="nsew", padx=(8, 2), pady=8)
        pane_a.grid_rowconfigure(1, weight=1)
        pane_a.grid_columnconfigure(0, weight=1)

        hdr_a = ctk.CTkFrame(pane_a, fg_color=self.button_bg, corner_radius=0, height=36)
        hdr_a.grid(row=0, column=0, sticky="ew")
        hdr_a.grid_propagate(False)
        self._cmp_title_a = ctk.CTkLabel(hdr_a, text="📄  Document A",
                                          font=ctk.CTkFont(family=self.FONT, size=12, weight="bold"),
                                          text_color="#ffffff")
        self._cmp_title_a.pack(side="left", padx=12, pady=8)

        self._cmp_text_a = tk.Text(
            pane_a, wrap="word", bg=self.input_bg, fg=self.input_fg,
            font=(self.FONT, 12), relief="flat", padx=12, pady=10,
            insertbackground=self.accent, selectbackground=self.accent,
            selectforeground="#ffffff", undo=True)
        self._cmp_text_a.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self._cmp_text_a.bind("<KeyRelease>", lambda e: self._cmp_update_wc())
        sb_a = ctk.CTkScrollbar(pane_a, command=self._cmp_text_a.yview)
        sb_a.grid(row=1, column=1, sticky="ns", pady=8)
        self._cmp_text_a.configure(yscrollcommand=sb_a.set)
        self._cmp_wc_a = ctk.CTkLabel(pane_a, text="Words: 0",
                                       font=ctk.CTkFont(family=self.FONT, size=10),
                                       text_color=self.muted_text)
        self._cmp_wc_a.grid(row=2, column=0, sticky="e", padx=10, pady=(2, 6))

        # ── Document B pane ─────────────────────────────────────────
        pane_b = ctk.CTkFrame(outer, fg_color=self.card_bg, corner_radius=0,
                               border_width=1, border_color="#2d2d4e")
        pane_b.grid(row=1, column=1, sticky="nsew", padx=(2, 2), pady=8)
        pane_b.grid_rowconfigure(1, weight=1)
        pane_b.grid_columnconfigure(0, weight=1)

        hdr_b = ctk.CTkFrame(pane_b, fg_color="#0f766e", corner_radius=0, height=36)
        hdr_b.grid(row=0, column=0, sticky="ew")
        hdr_b.grid_propagate(False)
        self._cmp_title_b = ctk.CTkLabel(hdr_b, text="📄  Document B",
                                          font=ctk.CTkFont(family=self.FONT, size=12, weight="bold"),
                                          text_color="#ffffff")
        self._cmp_title_b.pack(side="left", padx=12, pady=8)

        self._cmp_text_b = tk.Text(
            pane_b, wrap="word", bg=self.input_bg, fg=self.input_fg,
            font=(self.FONT, 12), relief="flat", padx=12, pady=10,
            insertbackground=self.accent, selectbackground="#0f766e",
            selectforeground="#ffffff", undo=True)
        self._cmp_text_b.grid(row=1, column=0, sticky="nsew")
        sb_b = ctk.CTkScrollbar(pane_b, command=self._cmp_text_b.yview)
        sb_b.grid(row=1, column=1, sticky="ns", pady=8)
        self._cmp_text_b.configure(yscrollcommand=sb_b.set)
        self._cmp_wc_b = ctk.CTkLabel(pane_b, text="Words: 0",
                                       font=ctk.CTkFont(family=self.FONT, size=10),
                                       text_color=self.muted_text)
        self._cmp_wc_b.grid(row=2, column=0, sticky="e", padx=10, pady=(2, 6))

        # ── Comparison Highlights sidebar ────────────────────────────
        sidebar = ctk.CTkFrame(outer, fg_color=self.sidebar_bg, corner_radius=0,
                                border_width=1, border_color="#2d2d4e",
                                width=320)
        sidebar.grid(row=1, column=2, sticky="nsew", padx=(2, 8), pady=8)
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(1, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        sb_hdr = ctk.CTkFrame(sidebar, fg_color="#4f46e5", corner_radius=0, height=36)
        sb_hdr.grid(row=0, column=0, sticky="ew")
        sb_hdr.grid_propagate(False)
        ctk.CTkLabel(sb_hdr, text="✦  Comparison Highlights",
                     font=ctk.CTkFont(family=self.FONT, size=12, weight="bold"),
                     text_color="#ffffff").pack(side="left", padx=12, pady=8)

        self._cmp_highlights_frame = ctk.CTkScrollableFrame(
            sidebar, fg_color=self.sidebar_bg, corner_radius=0)
        self._cmp_highlights_frame.grid(row=1, column=0, sticky="nsew")
        self._cmp_highlights_frame.grid_columnconfigure(0, weight=1)

        # populate from existing doc_a / doc_b if already loaded
        if self.document_a:
            self._cmp_text_a.insert("1.0", self.document_a.get("text", ""))
            self._cmp_title_a.configure(
                text=f"📄  {self.document_a.get('name', 'Document A')}")
        if self.document_b:
            self._cmp_text_b.insert("1.0", self.document_b.get("text", ""))
            self._cmp_title_b.configure(
                text=f"📄  {self.document_b.get('name', 'Document B')}")
        self._cmp_update_wc()
        self._cmp_refresh_highlights()

    # ── helpers for the comparison view ─────────────────────────────
    def _cmp_load_a(self):
        path = filedialog.askopenfilename(
            title="Select Document A",
            filetypes=[("Supported files", "*.txt *.pdf *.docx"), ("All files", "*.*")])
        if not path:
            return
        try:
            doc = load_document(path)
        except (ValueError, ImportError, OSError) as e:
            messagebox.showwarning("Load error", str(e))
            return
        self.document_a = {**doc, "source": doc["name"]}
        if hasattr(self, "_cmp_text_a") and self._cmp_text_a.winfo_exists():
            self._cmp_text_a.delete("1.0", "end")
            self._cmp_text_a.insert("1.0", doc["text"])
            self._cmp_title_a.configure(text=f"📄  {doc['name']}")
            self._cmp_update_wc()

    def _cmp_load_b(self):
        path = filedialog.askopenfilename(
            title="Select Document B",
            filetypes=[("Supported files", "*.txt *.pdf *.docx"), ("All files", "*.*")])
        if not path:
            return
        try:
            doc = load_document(path)
        except (ValueError, ImportError, OSError) as e:
            messagebox.showwarning("Load error", str(e))
            return
        self.document_b = {**doc, "source": doc["name"]}
        if hasattr(self, "_cmp_text_b") and self._cmp_text_b.winfo_exists():
            self._cmp_text_b.delete("1.0", "end")
            self._cmp_text_b.insert("1.0", doc["text"])
            self._cmp_title_b.configure(text=f"📄  {doc['name']}")
            self._cmp_update_wc()

    def _cmp_clear(self):
        if hasattr(self, "_cmp_text_a") and self._cmp_text_a.winfo_exists():
            self._cmp_text_a.delete("1.0", "end")
        if hasattr(self, "_cmp_text_b") and self._cmp_text_b.winfo_exists():
            self._cmp_text_b.delete("1.0", "end")
        self.document_a = None
        self.document_b = None
        self.current_result = None
        if hasattr(self, "_cmp_badge_var"):
            self._cmp_badge_var.set("—")
        self._cmp_update_wc()
        self._cmp_refresh_highlights()

    def _cmp_update_wc(self):
        if hasattr(self, "_cmp_text_a") and self._cmp_text_a.winfo_exists():
            wc = len(WORD_RE.findall(self._cmp_text_a.get("1.0", "end")))
            self._cmp_wc_a.configure(text=f"Words: {wc}")
        if hasattr(self, "_cmp_text_b") and self._cmp_text_b.winfo_exists():
            wc = len(WORD_RE.findall(self._cmp_text_b.get("1.0", "end")))
            self._cmp_wc_b.configure(text=f"Words: {wc}")

    def _cmp_run(self):
        """Run comparison, highlight both panes, refresh sidebar."""
        if not (hasattr(self, "_cmp_text_a") and self._cmp_text_a.winfo_exists()):
            return
        text_a = self._cmp_text_a.get("1.0", "end").strip()
        text_b = self._cmp_text_b.get("1.0", "end").strip()
        if not text_a or not text_b:
            messagebox.showinfo("Missing content",
                                "Please provide text in both Document A and Document B.")
            return

        doc_a = create_manual_document(text_a, name=self.document_a.get("name", "Document A") if self.document_a else "Document A")
        doc_b = create_manual_document(text_b, name=self.document_b.get("name", "Document B") if self.document_b else "Document B")
        self.document_a = doc_a
        self.document_b = doc_b
        self.current_result = compare_documents([doc_a, doc_b])

        sim = self.current_result["average_similarity"]
        self._cmp_badge_var.set(f"{sim}%")
        color = self.color_plagiarized if sim > 30 else (self.color_partial if sim > 10 else self.color_unique)
        self._cmp_badge_lbl.configure(text_color=color)

        # apply highlights to both text panes
        self._cmp_clear_tags()
        comp = self.current_result["comparisons"][0] if self.current_result["comparisons"] else None
        if comp:
            for m in comp.get("sentence_matches", []):
                self._cmp_highlight(self._cmp_text_a, m["a"], "sim")
                self._cmp_highlight(self._cmp_text_b, m["b"], "sim")
            for m in comp.get("paragraph_matches", []):
                self._cmp_highlight(self._cmp_text_a, m["a"], "sim")
                self._cmp_highlight(self._cmp_text_b, m["b"], "sim")
            for m in comp.get("paraphrase_matches", []):
                self._cmp_highlight(self._cmp_text_a, m["a"], "para")
                self._cmp_highlight(self._cmp_text_b, m["b"], "para")

        self._cmp_refresh_highlights()
        self._set_status(f"Comparison complete — {sim}% similarity")

    def _cmp_clear_tags(self):
        for widget in (self._cmp_text_a, self._cmp_text_b):
            for tag in ("sim", "para", "diff_a", "diff_b"):
                widget.tag_remove(tag, "1.0", "end")
        # configure tag colours once
        sim_bg, sim_fg   = "#14532d", "#bbf7d0"
        para_bg, para_fg = "#7c2d12", "#fed7aa"
        diff_bg, diff_fg = "#1e1b4b", "#c7d2fe"
        for widget in (self._cmp_text_a, self._cmp_text_b):
            widget.tag_configure("sim",    background=sim_bg,  foreground=sim_fg)
            widget.tag_configure("para",   background=para_bg, foreground=para_fg)
            widget.tag_configure("diff_a", background=diff_bg, foreground=diff_fg)
            widget.tag_configure("diff_b", background=diff_bg, foreground=diff_fg)

    def _cmp_highlight(self, widget, needle, tag):
        needle = needle.strip()
        if not needle:
            return
        start = "1.0"
        while True:
            idx = widget.search(needle, start, stopindex="end", nocase=True)
            if not idx:
                break
            end = f"{idx}+{len(needle)}c"
            widget.tag_add(tag, idx, end)
            start = end

    def _cmp_refresh_highlights(self):
        """Rebuild the Comparison Highlights sidebar."""
        if not (hasattr(self, "_cmp_highlights_frame")
                and self._cmp_highlights_frame.winfo_exists()):
            return
        for w in self._cmp_highlights_frame.winfo_children():
            w.destroy()

        frame = self._cmp_highlights_frame

        if not self.current_result or not self.current_result.get("comparisons"):
            self._cmp_sidebar_empty(frame)
            return

        comp = self.current_result["comparisons"][0]
        sim_sentences  = comp.get("sentence_matches", [])
        para_matches   = comp.get("paragraph_matches", [])
        para_phrases   = comp.get("paraphrase_matches", [])
        text_a = self.document_a.get("text", "") if self.document_a else ""
        text_b = self.document_b.get("text", "") if self.document_b else ""

        # collect matched sentence keys to find unique sentences
        matched_keys_a = {clean_text(m["a"]) for m in sim_sentences + para_matches}
        matched_keys_b = {clean_text(m["b"]) for m in sim_sentences + para_matches}
        unique_a = [s for s in split_sentences(text_a) if clean_text(s) not in matched_keys_a][:6]
        unique_b = [s for s in split_sentences(text_b) if clean_text(s) not in matched_keys_b][:6]

        # ── Summary row ────────────────────────────────────────────
        self._cmp_sb_section(frame, "📊  Overview", self.accent)
        sim_pct = self.current_result["average_similarity"]
        col = (self.color_plagiarized if sim_pct > 30
               else self.color_partial if sim_pct > 10 else self.color_unique)
        ov = ctk.CTkFrame(frame, fg_color=self.card_bg, corner_radius=10)
        ov.pack(fill="x", padx=8, pady=(0, 6))
        ctk.CTkLabel(ov, text=f"{sim_pct}%",
                     font=ctk.CTkFont(family=self.FONT, size=28, weight="bold"),
                     text_color=col).pack(pady=(10, 0))
        ctk.CTkLabel(ov, text="Overall Similarity",
                     font=ctk.CTkFont(family=self.FONT, size=11),
                     text_color=self.muted_text).pack(pady=(0, 4))
        ctk.CTkFrame(ov, fg_color="#2d2d4e", height=1).pack(fill="x", padx=10)
        for lbl, cnt in (("Exact matches", len(sim_sentences)),
                         ("Paraphrase matches", len(para_phrases)),
                         ("Paragraph matches", len(para_matches))):
            r = ctk.CTkFrame(ov, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(r, text=lbl,
                         font=ctk.CTkFont(family=self.FONT, size=11),
                         text_color=self.muted_text).pack(side="left")
            ctk.CTkLabel(r, text=str(cnt),
                         font=ctk.CTkFont(family=self.FONT, size=11, weight="bold"),
                         text_color=self.title_text).pack(side="right")
        ctk.CTkLabel(ov, text="").pack(pady=4)

        # ── Key Similarities ───────────────────────────────────────
        all_sim = sim_sentences[:5] + [{"a": m["a"], "b": m["b"], "score": None} for m in para_phrases[:3]]
        self._cmp_sb_section(frame, "✓  Key Similarities", self.color_unique)
        if not all_sim:
            self._cmp_sb_item(frame, "No matching sentences found.",
                              self.muted_text, None, is_sim=True)
        for m in all_sim:
            snippet = (m["a"][:90] + "…") if len(m["a"]) > 90 else m["a"]
            score_txt = f"  {m['score']}%" if m.get("score") else ""
            self._cmp_sb_item(frame, snippet + score_txt, self.color_unique, "✓", is_sim=True)

        # ── Key Differences ────────────────────────────────────────
        self._cmp_sb_section(frame, "✗  Key Differences", self.color_plagiarized)
        if not unique_a and not unique_b:
            self._cmp_sb_item(frame, "Documents appear largely identical.",
                              self.muted_text, None, is_sim=False)
        for s in unique_a:
            snippet = (s[:90] + "…") if len(s) > 90 else s
            self._cmp_sb_item(frame, f"[A] {snippet}", "#93c5fd", "✗", is_sim=False)
        for s in unique_b:
            snippet = (s[:90] + "…") if len(s) > 90 else s
            self._cmp_sb_item(frame, f"[B] {snippet}", "#6ee7b7", "✗", is_sim=False)

    def _cmp_sidebar_empty(self, frame):
        ctk.CTkLabel(frame,
                     text="Load two documents and\nclick ⚡ Run Compare\nto see highlights.",
                     font=ctk.CTkFont(family=self.FONT, size=12),
                     text_color=self.muted_text,
                     justify="center").pack(pady=40, padx=12)

    def _cmp_sb_section(self, parent, title, color):
        hdr = ctk.CTkFrame(parent, fg_color=color, corner_radius=8, height=30)
        hdr.pack(fill="x", padx=8, pady=(10, 4))
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text=title,
                     font=ctk.CTkFont(family=self.FONT, size=11, weight="bold"),
                     text_color="#0d0d1a").pack(side="left", padx=10, pady=6)

    def _cmp_sb_item(self, parent, text, color, icon, is_sim):
        bg = "#14532d" if is_sim else "#1e1b4b"
        row = ctk.CTkFrame(parent, fg_color=bg, corner_radius=8)
        row.pack(fill="x", padx=8, pady=2)
        if icon:
            ctk.CTkLabel(row, text=icon,
                         font=ctk.CTkFont(family=self.FONT, size=13, weight="bold"),
                         text_color=color, width=20).pack(side="left", padx=(8, 4), pady=6)
        ctk.CTkLabel(row, text=text,
                     font=ctk.CTkFont(family=self.FONT, size=10),
                     text_color=color,
                     wraplength=260, justify="left", anchor="w").pack(
            side="left", fill="x", expand=True, padx=(0, 8), pady=6)

    # ------------------------------------------------------------------
    def draw_source_breakdown(self, parent):
        if not self.current_result or not self.current_result.get("comparisons"):
            ctk.CTkLabel(parent, text="No sources found in analysis.",
                         text_color=self.muted_text, font=ctk.CTkFont(family=self.FONT, size=13)).pack(anchor="w", padx=20, pady=10)
            return

        sources_breakdown = []
        for comp in self.current_result["comparisons"]:
            if comp.get("source"):
                sources_breakdown.append((comp["source"], comp["plagiarism"]))

        if not sources_breakdown:
            ctk.CTkLabel(parent, text="No specific sources detected.",
                         text_color=self.muted_text, font=ctk.CTkFont(family=self.FONT, size=13)).pack(anchor="w", padx=20, pady=10)
            return

        for source_name, contribution in sorted(sources_breakdown, key=lambda x: x[1], reverse=True):
            pct = round(contribution, 1)
            source_row = ctk.CTkFrame(parent, fg_color=self.input_bg, corner_radius=10)
            source_row.pack(fill="x", padx=20, pady=5)
            ctk.CTkLabel(source_row, text=source_name,
                         font=ctk.CTkFont(family=self.FONT, size=13, weight="bold"),
                         text_color=self.title_text).pack(anchor="w", padx=14, pady=(10, 4))
            bar_frame = ctk.CTkFrame(source_row, fg_color="#2d2d4e", corner_radius=6, height=14)
            bar_frame.pack(fill="x", padx=14, pady=(0, 4))
            fill_pct = min(100, pct) / 100
            if fill_pct > 0:
                ctk.CTkProgressBar(bar_frame, width=fill_pct * 400,
                                   progress_color=self.color_plagiarized, height=14).place(relx=0, rely=0)
            ctk.CTkLabel(source_row, text=f"{pct}%",
                         font=ctk.CTkFont(family=self.FONT, size=12, weight="bold"),
                         text_color=self.color_plagiarized).pack(anchor="e", padx=14, pady=(0, 8))

    def draw_document_preview(self, parent):
        if not self.current_result or not self.current_result.get("comparisons"):
            ctk.CTkLabel(parent, text="No comparison data available.", text_color=self.muted_text, font=ctk.CTkFont(family="Segoe UI", size=12)).pack(anchor="w", padx=20, pady=10)
            return

        docs = self.current_result["documents"]
        comparison = max(self.current_result["comparisons"], key=lambda item: item["similarity"])
        left_idx = min(comparison["left_index"], len(docs) - 1)
        right_idx = min(comparison["right_index"], len(docs) - 1)
        left_doc = docs[left_idx]
        # In single-doc mode both indices are the same; show doc vs matched source name
        right_doc = docs[right_idx]
        right_title = comparison.get("right_name", right_doc["name"])

        preview_inner = ctk.CTkFrame(parent, fg_color=self.panel_bg)
        preview_inner.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        preview_inner.grid_columnconfigure((0, 1), weight=1)

        left = self.document_text_box(preview_inner, left_doc["name"], left_doc["text"], 0, 0)
        right = self.document_text_box(preview_inner, right_title, right_doc["text"], 0, 1)

        for match in comparison.get("sentence_matches", []):
            self.highlight_text_with_color(left, match["a"], self.color_plagiarized)
            self.highlight_text_with_color(right, match["b"], self.color_plagiarized)
        for match in comparison.get("paragraph_matches", []):
            self.highlight_text_with_color(left, match["a"], self.color_plagiarized)
            self.highlight_text_with_color(right, match["b"], self.color_plagiarized)
        for match in comparison.get("paraphrase_matches", []):
            self.highlight_text_with_color(left, match["a"], self.color_partial)
            self.highlight_text_with_color(right, match["b"], self.color_partial)

    def copy_summary_to_clipboard(self):
        if not self.current_result:
            messagebox.showinfo("Nothing to copy", "Run a scan first.")
            return
        lines = [
            f"Plagiarism & Similarity Summary",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Average Similarity: {self.current_result['average_similarity']}%",
            f"Average Plagiarism: {self.average_plagiarism()}%",
            f"Exact Matches: {self.calculate_exact_match_percentage()}%",
            f"Partial Matches: {self.calculate_partial_match_percentage()}%",
        ]
        for comp in self.current_result["comparisons"]:
            lines.append(f"  {comp['left_name']} vs {comp['right_name']}: {comp['similarity']}% similarity, {comp['plagiarism']}% plagiarism")
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        messagebox.showinfo("Copied", "Summary copied to clipboard.")

    def check_grammar(self):
        messagebox.showinfo("Grammar Check", "Grammar checking feature will be available in the next update.")

    def detect_ai(self):
        messagebox.showinfo("AI Detector", "AI content detection feature will be available in the next update.")

    def export_csv(self):
        if not self.current_result:
            messagebox.showinfo("No results", "Run a scan before exporting.")
            return
        try:
            import csv
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = REPORTS_DIR / f"plagiarism_report_{timestamp}.csv"
            with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Metric", "Value"])
                writer.writerow(["Average Similarity", f"{self.current_result['average_similarity']}%"])
                writer.writerow(["Average Plagiarism", f"{self.average_plagiarism()}%"])
                writer.writerow(["Exact Matches", f"{self.calculate_exact_match_percentage()}%"])
                writer.writerow(["Partial Matches", f"{self.calculate_partial_match_percentage()}%"])
                writer.writerow([])
                writer.writerow(["Source", "Similarity %", "Plagiarism %"])
                for comp in self.current_result["comparisons"]:
                    writer.writerow([comp.get("source", "Unknown"), comp["similarity"], comp["plagiarism"]])
            messagebox.showinfo("Report exported", f"CSV report saved to:\n{output_path}")
        except Exception as error:
            messagebox.showerror("Export failed", str(error))

    def highlight_text_with_color(self, widget, needle, color):
        if not needle.strip():
            return
        widget.configure(state="normal")
        start = "1.0"
        while True:
            index = widget.search(needle.strip(), start, stopindex="end", nocase=True)
            if not index:
                break
            end = f"{index}+{len(needle.strip())}c"
            widget.tag_add("highlight_temp", index, end)
            widget.tag_configure("highlight_temp", background=color, foreground="#ffffff")
            start = end
        widget.configure(state="disabled")

    def comparison_card(self, parent, comparison, row):
        card = ctk.CTkFrame(parent, fg_color=self.card_bg, corner_radius=8)
        card.grid(row=row, column=0, columnspan=2, sticky="ew", pady=6)
        ctk.CTkLabel(
            card,
            text=f"{comparison['left_name']}  vs  {comparison['right_name']}",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.title_text,
        ).pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            card,
            text=(
                f"Similarity: {comparison['similarity']}% | Plagiarism: {comparison['plagiarism']}% | "
                f"Exact matches: {len(comparison['sentence_matches'])} | "
                f"Paraphrase matches: {len(comparison.get('paraphrase_matches', []))}"
            ),
            text_color=self.muted_text,
        ).pack(anchor="w", padx=14, pady=(0, 12))
        if comparison.get("source"):
            ctk.CTkLabel(
                card,
                text=f"Matched source: {comparison['source']}",
                text_color=self.accent,
                font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(anchor="w", padx=14, pady=(0, 12))

    def duplicate_list(self, parent, row):
        frame = ctk.CTkFrame(parent, fg_color=self.card_bg, corner_radius=8)
        frame.grid(row=row, column=0, columnspan=2, sticky="ew")
        found = False
        for index, duplicates in enumerate(self.current_result["duplicates"]):
            document_name = self.current_result["documents"][index]["name"]
            if duplicates:
                found = True
                ctk.CTkLabel(frame, text=document_name, font=ctk.CTkFont(size=14, weight="bold"), text_color=self.title_text).pack(anchor="w", padx=14, pady=(12, 4))
                for duplicate in duplicates[:8]:
                    ctk.CTkLabel(frame, text=f"{duplicate['count']}x - {duplicate['sentence']}", text_color=self.muted_text, wraplength=900, justify="left").pack(anchor="w", padx=24, pady=2)
        if not found:
            ctk.CTkLabel(frame, text="No repeated sentences found within the uploaded documents.", text_color=self.muted_text).pack(anchor="w", padx=14, pady=14)

    def side_by_side(self, parent, row):
        if not self.current_result["comparisons"]:
            return

        comparison = max(self.current_result["comparisons"], key=lambda item: item["similarity"])
        left_doc = self.current_result["documents"][comparison["left_index"]]
        right_doc = self.current_result["documents"][comparison["right_index"]]

        left = self.document_text_box(parent, left_doc["name"], left_doc["text"], row, 0)
        right = self.document_text_box(parent, right_doc["name"], right_doc["text"], row, 1)

        for match in comparison["sentence_matches"]:
            self.highlight_text(left, match["a"], "sentence_match")
            self.highlight_text(right, match["b"], "sentence_match")
        for match in comparison["paragraph_matches"]:
            self.highlight_text(left, match["a"], "paragraph_match")
            self.highlight_text(right, match["b"], "paragraph_match")
        for match in comparison.get("paraphrase_matches", []):
            self.highlight_text(left, match["a"], "paraphrase_match")
            self.highlight_text(right, match["b"], "paraphrase_match")

    def document_text_box(self, parent, title, text, row, column):
        frame = ctk.CTkFrame(parent, fg_color=self.card_bg, corner_radius=12,
                              border_width=1, border_color="#2d2d4e")
        frame.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(family=self.FONT, size=14, weight="bold"),
                     text_color=self.title_text).pack(anchor="w", padx=14, pady=(14, 4))
        widget = tk.Text(
            frame,
            height=18,
            wrap="word",
            bg=self.input_bg,
            fg=self.input_fg,
            font=(self.FONT, 12),
            insertbackground=self.accent,
            relief="flat",
            padx=12,
            pady=10,
            selectbackground=self.accent,
            selectforeground="#ffffff",
        )
        widget.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        widget.insert("1.0", text)
        widget.tag_configure("sentence_match", background="#7f1d1d", foreground="#fecaca")
        widget.tag_configure("paragraph_match", background="#7c2d12", foreground="#fed7aa")
        widget.tag_configure("paraphrase_match", background="#312e81", foreground="#bfdbfe")
        widget.configure(state="disabled")
        return widget

    def highlight_text(self, widget, needle, tag):
        if not needle.strip():
            return
        widget.configure(state="normal")
        start = "1.0"
        while True:
            index = widget.search(needle.strip(), start, stopindex="end", nocase=True)
            if not index:
                break
            end = f"{index}+{len(needle.strip())}c"
            widget.tag_add(tag, index, end)
            start = end
        widget.configure(state="disabled")

    def export_report(self):
        if not self.current_result:
            messagebox.showinfo("No results", "Run a scan before exporting a report.")
            return
        try:
            path = generate_pdf_report(self.current_result)
        except ImportError as error:
            messagebox.showerror("Missing dependency", str(error))
            return
        except Exception as error:
            messagebox.showerror("Report failed", str(error))
            return
        messagebox.showinfo("Report generated", f"PDF report saved to:\n{path}")

    def show_history(self):
        self.set_active_nav("History")
        self.clear_container()

        body = ctk.CTkScrollableFrame(self.container, fg_color=self.panel_bg)
        body.pack(fill="both", expand=True, padx=24, pady=18)
        body.grid_columnconfigure(0, weight=1)

        hdr_f = ctk.CTkFrame(body, fg_color="transparent")
        hdr_f.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(hdr_f, text="🕐  Scan History",
                     font=ctk.CTkFont(family=self.FONT, size=22, weight="bold"),
                     text_color=self.title_text).pack(side="left")

        records = load_history()
        clear_btn_frame = ctk.CTkFrame(body, fg_color="transparent")
        clear_btn_frame.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkButton(clear_btn_frame, text="🗑  Clear All History",
                      command=lambda: [save_history([]), self.show_history()],
                      fg_color="#7f1d1d", hover_color="#991b1b", text_color="#ffffff",
                      corner_radius=10, height=38,
                      font=ctk.CTkFont(family=self.FONT, size=12, weight="bold")).pack(side="left")

        if not records:
            ctk.CTkLabel(body, text="No history records yet. Run a scan to see results here.",
                         text_color=self.muted_text,
                         font=ctk.CTkFont(family=self.FONT, size=14)).grid(row=2, column=0, sticky="w", pady=10)
            return
        for index, record in enumerate(records, start=2):
            self.history_row(body, record, index)

    def history_row(self, parent, record, row):
        card = ctk.CTkFrame(parent, fg_color=self.card_bg, corner_radius=12,
                             border_width=1, border_color="#2d2d4e")
        card.grid(row=row, column=0, columnspan=3, sticky="ew", pady=6)
        ctk.CTkLabel(card,
                     text=f"🕐  {record.get('timestamp', 'Unknown time')}",
                     font=ctk.CTkFont(family=self.FONT, size=14, weight="bold"),
                     text_color=self.title_text).pack(anchor="w", padx=16, pady=(14, 2))
        files = ", ".join(record.get("files", []))
        ctk.CTkLabel(card, text=files,
                     text_color=self.muted_text, wraplength=900, justify="left",
                     font=ctk.CTkFont(family=self.FONT, size=12)).pack(anchor="w", padx=16)
        ctk.CTkLabel(card,
                     text=f"Avg Similarity: {record.get('average_similarity', 0)}%  •  Avg Plagiarism: {record.get('average_plagiarism', 0)}%",
                     text_color=self.accent,
                     font=ctk.CTkFont(family=self.FONT, size=12, weight="bold")).pack(anchor="w", padx=16, pady=(4, 14))


def main():
    app = PlagiarismApp()
    app.mainloop()


if __name__ == "__main__":
    main()
