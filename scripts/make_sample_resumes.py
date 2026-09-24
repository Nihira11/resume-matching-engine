"""
Generate the two demo resumes that ship with the project.

    python -m scripts.make_sample_resumes

Both are fictional people with invented employers, so they can be shown
to anyone and committed to the repo. They exist so the UI can be
demonstrated without uploading a real CV -- and so the ATS parsability
check has something to disagree about:

* avery_chen_clean.pdf   -- single column, no tables, no images: 100/100
* jordan_blake_tables.pdf -- a genuinely ruled table plus an embedded
  image, which is what a real ATS parser mangles

Generated rather than hand-drawn so the layout that triggers each flag is
explicit in code, and can be regenerated if the detector changes.
"""
from __future__ import annotations

from pathlib import Path

import fitz

OUT_DIR = Path("data/samples/resumes")

CLEAN_BODY = [
    ("AVERY CHEN", 17, True),
    ("Sydney, NSW  |  avery.chen@example.com  |  linkedin.com/in/example", 9, False),
    ("", 9, False),
    ("EDUCATION", 12, True),
    ("Bachelor of Data Science - University of Technology Sydney", 10, False),
    ("Expected graduation: December 2026  |  Distinction average", 9, False),
    ("Relevant coursework: Statistics, Machine Learning, Database Systems,", 9, False),
    ("Data Visualisation, Predictive Analytics", 9, False),
    ("", 9, False),
    ("EXPERIENCE", 12, True),
    ("Data Analyst Intern - Brightwater Retail, Sydney  (Nov 2025 - Feb 2026)", 10, True),
    ("- Built SQL queries against a 12 million row sales database to answer", 9, False),
    ("  weekly merchandising questions", 9, False),
    ("- Automated a manual Excel report in Python (pandas), cutting a four hour", 9, False),
    ("  task to under ten minutes", 9, False),
    ("- Built a Power BI dashboard tracking stock turnover across 40 stores", 9, False),
    ("", 9, False),
    ("Student Data Assistant - UTS Analytics Lab  (Mar 2025 - Oct 2025)", 10, True),
    ("- Cleaned and reconciled survey data for three research projects", 9, False),
    ("- Ran hypothesis tests and regression analysis in R and reported findings", 9, False),
    ("", 9, False),
    ("PROJECTS", 12, True),
    ("Customer Churn Prediction - Python, scikit-learn, XGBoost", 10, True),
    ("- Trained gradient boosting and random forest models on 10,000 customers,", 9, False),
    ("  reaching 0.87 ROC-AUC, and explained drivers with SHAP", 9, False),
    ("", 9, False),
    ("Energy Demand Forecasting - Python, statsmodels", 10, True),
    ("- Built time series models to forecast daily demand, validated out of sample", 9, False),
    ("", 9, False),
    ("SKILLS", 12, True),
    ("Languages and tools: SQL, Python, R, Power BI, Tableau, Git, Excel", 9, False),
    ("Machine learning: scikit-learn, XGBoost, random forest, SHAP, clustering", 9, False),
    ("Statistics: hypothesis testing, regression analysis, forecasting, A/B testing", 9, False),
]

TABLED_HEADER = "Jordan Blake - Curriculum Vitae"
TABLED_FOOTER = "Jordan Blake  |  jordan.blake@example.com  |  page "

TABLED_INTRO = [
    ("JORDAN BLAKE", 16, True),
    ("Melbourne, VIC  |  jordan.blake@example.com  |  0400 000 000", 9, False),
    ("", 9, False),
    ("PROFILE", 12, True),
    ("Business analyst moving into data analytics, with four years across", 9, False),
    ("reporting, requirements gathering and stakeholder engagement.", 9, False),
    ("", 9, False),
    ("SKILLS MATRIX", 12, True),
]

SKILLS_TABLE = [
    ["Skill", "Level", "Years", "Last used"],
    ["SQL", "Advanced", "4", "2026"],
    ["Excel", "Advanced", "6", "2026"],
    ["Power BI", "Intermediate", "3", "2026"],
    ["Python", "Intermediate", "2", "2025"],
    ["Tableau", "Basic", "1", "2024"],
    ["Jira", "Advanced", "4", "2026"],
]

TABLED_REST = [
    ("EXPERIENCE", 12, True),
    ("Business Analyst - Kestrel Financial Services  (2022 - present)", 10, True),
    ("- Gathered requirements and wrote user stories for a payments platform", 9, False),
    ("- Built and maintained operational reporting in Power BI and Excel", 9, False),
    ("- Ran workshops with stakeholders across operations, risk and technology", 9, False),
    ("", 9, False),
    ("Reporting Analyst - Orchard Insurance  (2020 - 2022)", 10, True),
    ("- Produced monthly claims reporting from SQL Server", 9, False),
    ("- Automated reconciliation checks, reducing manual review time", 9, False),
    ("", 9, False),
    ("EDUCATION", 12, True),
    ("Bachelor of Commerce (Finance) - Monash University, 2019", 9, False),
]


def draw_lines(page, lines, x=60, y=70, leading=14):
    for text, size, bold in lines:
        if text:
            page.insert_text(
                (x, y), text, fontsize=size,
                fontname="hebo" if bold else "helv",
            )
        y += leading if text else leading * 0.6
    return y


def build_clean(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    draw_lines(page, CLEAN_BODY)
    doc.save(str(path))
    doc.close()


def build_tabled(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()

    # repeated header and footer: the third thing an ATS trips on
    page.insert_text((60, 40), TABLED_HEADER, fontsize=8, fontname="helv")
    page.insert_text((60, 800), TABLED_FOOTER + "1", fontsize=8, fontname="helv")

    y = draw_lines(page, TABLED_INTRO, y=70)

    # a genuinely ruled table -- drawn lines, not whitespace alignment
    left, right = 60, 400
    col_width = (right - left) / 4
    row_height = 18
    top = y
    for row_index, row in enumerate(SKILLS_TABLE):
        row_top = top + row_index * row_height
        page.draw_line(fitz.Point(left, row_top), fitz.Point(right, row_top), width=0.6)
        for col_index, cell in enumerate(row):
            page.insert_text(
                (left + col_index * col_width + 4, row_top + 12),
                cell, fontsize=9,
                fontname="hebo" if row_index == 0 else "helv",
            )
    bottom = top + len(SKILLS_TABLE) * row_height
    page.draw_line(fitz.Point(left, bottom), fitz.Point(right, bottom), width=0.6)
    for col_index in range(5):
        x = left + col_index * col_width
        page.draw_line(fitz.Point(x, top), fitz.Point(x, bottom), width=0.6)

    # an embedded image: a headshot placeholder, which ATS parsers drop
    photo = fitz.Rect(430, 70, 530, 190)
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 120))
    pixmap.set_rect(pixmap.irect, (210, 214, 224))
    page.insert_image(photo, pixmap=pixmap)
    page.insert_text((446, 205), "photo", fontsize=8, fontname="helv")

    draw_lines(page, TABLED_REST, y=bottom + 30)

    second = doc.new_page()
    second.insert_text((60, 40), TABLED_HEADER, fontsize=8, fontname="helv")
    second.insert_text((60, 800), TABLED_FOOTER + "2", fontsize=8, fontname="helv")
    draw_lines(second, [
        ("CERTIFICATIONS", 12, True),
        ("- Certified Business Analysis Professional (CBAP), 2023", 9, False),
        ("- Microsoft Power BI Data Analyst Associate, 2024", 9, False),
        ("", 9, False),
        ("REFEREES", 12, True),
        ("Available on request.", 9, False),
    ], y=70)

    doc.save(str(path))
    doc.close()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build_clean(OUT_DIR / "avery_chen_clean.pdf")
    build_tabled(OUT_DIR / "jordan_blake_tables.pdf")

    from src.ingestion.ats_parsability import check_parsability

    for path in sorted(OUT_DIR.glob("*.pdf")):
        result = check_parsability(str(path))
        print(f"  {path.name:28} {result.score:5.0f}/100  "
              f"{'; '.join(f.split('–')[0].strip() for f in result.flags) or 'clean'}")


if __name__ == "__main__":
    main()
