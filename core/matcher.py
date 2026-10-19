"""CV <-> job-description matcher.

Extracts text from a resume (PDF / DOCX / TXT), finds the skill keywords a job
description asks for, and reports how many of those your CV already covers plus
the ones it is missing. Deliberately simple and transparent: it works off a
curated skills vocabulary (edit SKILL_KEYWORDS to taste) so the match score is
explainable rather than a black box.
"""

from __future__ import annotations

import re
from pathlib import Path

# --------------------------------------------------------------------------- #
# Skills vocabulary. Add anything you want scored. Multi-word phrases are fine.
# --------------------------------------------------------------------------- #
SKILL_KEYWORDS: tuple[str, ...] = (
    # Languages
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang",
    "rust", "scala", "r", "sql", "bash", "shell", "kotlin", "swift", "ruby",
    # Data / analytics
    "etl", "elt", "data pipeline", "data pipelines", "data warehouse", "data lake",
    "data modeling", "data modelling", "dbt", "airflow", "spark", "pyspark",
    "hadoop", "kafka", "snowflake", "databricks", "bigquery", "redshift",
    "power bi", "powerbi", "power query", "tableau", "looker", "alteryx",
    "excel", "pandas", "numpy", "dax", "ssrs", "ssis",
    # ML / AI
    "machine learning", "deep learning", "nlp", "llm", "llms", "genai",
    "generative ai", "pytorch", "tensorflow", "scikit-learn", "sklearn",
    "mlops", "mcp", "rag", "langchain", "hugging face", "transformers",
    "model deployment", "feature engineering", "prompt engineering",
    # Cloud / infra
    "aws", "azure", "gcp", "google cloud", "ec2", "s3", "lambda", "cloudformation",
    "terraform", "ansible", "kubernetes", "k8s", "docker", "helm", "linux",
    "ci/cd", "cicd", "jenkins", "github actions", "gitlab ci", "devops",
    "site reliability", "sre", "observability", "prometheus", "grafana",
    "microservices", "serverless", "rest api", "graphql", "grpc",
    # Backend / web
    "fastapi", "flask", "django", "node.js", "nodejs", "express", "react",
    "postgres", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    # Practices
    "agile", "scrum", "unit testing", "tdd", "git", "object oriented",
    "distributed systems", "system design", "data structures", "algorithms",
    # Accounting / finance / tax (relevant to the user's background)
    "gaap", "audit", "tax", "financial modeling", "reconciliation",
    "accounts receivable", "accounts payable", "variance analysis",
)


def extract_text(path: str | Path) -> str:
    """Return plain text from a PDF, DOCX, or TXT resume."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            return _extract_pdf(path)
        if suffix in {".docx"}:
            return _extract_docx(path)
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # never let a bad file crash the UI
        return f""


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(path: Path) -> str:
    import docx  # python-docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def _normalize(text: str) -> str:
    """Lowercase and pad with spaces so phrase lookups are word-boundary-ish."""
    lowered = re.sub(r"[^a-z0-9+#./ ]+", " ", text.lower())
    collapsed = re.sub(r"\s+", " ", lowered)
    return f" {collapsed} "


def _present(keyword: str, normalized_text: str) -> bool:
    # Use lexical boundaries rather than literal surrounding spaces. The old
    # check missed sentence-final skills such as "Kubernetes." because dots
    # are intentionally preserved for vocabulary entries such as "node.js".
    phrase = r"\s+".join(re.escape(part) for part in keyword.lower().split())
    return bool(re.search(rf"(?<![a-z0-9+#]){phrase}(?![a-z0-9+#])", normalized_text))


def keywords_in(text: str) -> set[str]:
    """Which vocabulary skills appear in the given text."""
    normalized = _normalize(text)
    return {kw for kw in SKILL_KEYWORDS if _present(kw, normalized)}


def _evidence(text: str, keyword: str, radius: int = 90) -> str:
    """Return a short source excerpt around a keyword occurrence."""
    phrase = r"\s+".join(re.escape(part) for part in keyword.split())
    pattern = re.compile(rf"(?<![a-z0-9]){phrase}(?![a-z0-9])", re.IGNORECASE)
    match = pattern.search(text or "")
    if not match:
        return ""
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    excerpt = " ".join(text[start:end].split())
    if start:
        excerpt = "…" + excerpt
    if end < len(text):
        excerpt += "…"
    return excerpt


def analyze_jd(jd_text: str) -> dict:
    """Extract JD skills and evidence without claiming a resume comparison."""
    jd_skills = sorted(keywords_in(jd_text))
    return {
        "match": None,
        "matched": [],
        "missing": [],
        "extracted": jd_skills,
        "keyword_details": [
            {
                "keyword": keyword,
                "matched": None,
                "jd_evidence": _evidence(jd_text, keyword),
                "resume_evidence": "",
            }
            for keyword in jd_skills
        ],
        "matched_count": 0,
        "jd_skill_count": len(jd_skills),
        "method": "skills-vocabulary-v2",
        "confidence": (
            "unavailable" if not jd_skills else "limited" if len(jd_skills) < 4 else "standard"
        ),
        "jd_chars": len(jd_text or ""),
        "resume_chars": 0,
    }


def score(cv_text: str, jd_text: str) -> dict:
    """Compare a CV against a job description.

    Returns {match, matched, missing, jd_skill_count}.
    match is the percentage of the JD's skills that the CV already has.
    """
    jd_skills = keywords_in(jd_text)
    if not jd_skills:
        result = analyze_jd(jd_text)
        result["resume_chars"] = len(cv_text or "")
        return result

    cv_skills = keywords_in(cv_text)
    matched = sorted(jd_skills & cv_skills)
    missing = sorted(jd_skills - cv_skills)
    match = round(100 * len(matched) / len(jd_skills))
    details = [
        {
            "keyword": keyword,
            "matched": keyword in cv_skills,
            "jd_evidence": _evidence(jd_text, keyword),
            "resume_evidence": _evidence(cv_text, keyword) if keyword in cv_skills else "",
        }
        for keyword in sorted(jd_skills)
    ]
    return {
        "match": match,
        "matched": matched,
        "missing": missing,
        "extracted": sorted(jd_skills),
        "keyword_details": details,
        "matched_count": len(matched),
        "jd_skill_count": len(jd_skills),
        "method": "skills-vocabulary-v2",
        "confidence": "limited" if len(jd_skills) < 4 else "standard",
        "jd_chars": len(jd_text or ""),
        "resume_chars": len(cv_text or ""),
    }
