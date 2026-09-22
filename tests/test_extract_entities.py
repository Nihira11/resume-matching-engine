from src.nlp.extract_entities import (
    extract_education,
    extract_titles,
    extract_years_experience,
)


def test_extract_years_experience_range():
    text = "Looking for a candidate with 3-5 years of experience in data science."
    assert extract_years_experience(text) == [5]


def test_extract_years_experience_plus():
    text = "5+ years experience required."
    assert extract_years_experience(text) == [5]


def test_extract_years_experience_multiple():
    text = "2 years experience preferred, though 4+ years is ideal."
    assert extract_years_experience(text) == [4, 2]


def test_extract_education_bachelor():
    text = "Bachelor of Advanced Computing, University of Sydney"
    result = extract_education(text)
    assert any("Bachelor" in r for r in result)


def test_extract_education_abbreviated():
    text = "B.Sc in Computer Science, expected 2026"
    result = extract_education(text)
    assert result


def test_extract_education_associate_with_colon():
    text = "Associate : Accounting City , State , USA"
    result = extract_education(text)
    assert result
    assert "Accounting" in result[0]


def test_extract_education_associate_degree_phrase():
    text = "Associate's Degree in Business Administration"
    result = extract_education(text)
    assert result


def test_extract_education_associate_no_line_bleed():
    text = "Associate : Accounting City , State , USA\nManagerial oversight of reports."
    result = extract_education(text)
    assert result
    assert "Managerial" not in result[0]


def test_extract_education_no_false_positive_on_associate_job_title():
    # this was a real bug found by validating against the Kaggle NER dataset:
    # bare "Associate" in a job title line was being misread as a degree
    text = "Application Development Associate - Accenture"
    assert extract_education(text) == []


def test_extract_education_no_false_positive_on_associate_consultant():
    text = "Senior Associate Consultant - Infosys Limited"
    assert extract_education(text) == []


def test_extract_titles_keyword_match():
    text = "Data Analyst Intern\nSome unrelated line about hobbies\nSenior Software Engineer"
    titles = extract_titles(text)
    assert "Data Analyst Intern" in titles
    assert "Senior Software Engineer" in titles


def test_extract_titles_skips_long_lines():
    long_line = "This is a very long bullet point describing a project that happens to mention engineer somewhere in the middle of it"
    titles = extract_titles(long_line)
    assert titles == []


def test_extract_titles_no_substring_false_positive():
    text = "Directorate which previously did not exist.\nManagerial oversight of reports."
    titles = extract_titles(text)
    assert titles == []

def test_extract_years_experience_decimal():
    # known limitation until fixed: the "8" in "6.8" was matched on its own
    text = "Total IT experience 6.8 years"
    assert extract_years_experience(text) == [6.8]


def test_extract_years_experience_decimal_hyphenated():
    text = "Experience: 3.2-years in mainframe support"
    assert extract_years_experience(text) == [3.2]


def test_extract_years_experience_decimal_range():
    text = "2.5 to 4.5 years of experience"
    assert extract_years_experience(text) == [4.5]


def test_extract_years_experience_whole_numbers_stay_int():
    result = extract_years_experience("5+ years experience required.")
    assert result == [5]
    assert isinstance(result[0], int)


def test_extract_titles_general_workforce():
    text = (
        "Staff Accountant\n"
        "Administrative Assistant\n"
        "Maintenance Technician\n"
        "Customer Service Representative\n"
        "Compliance Officer"
    )
    titles = extract_titles(text)
    assert titles == text.splitlines()


def test_extract_titles_general_workforce_no_substring_false_positive():
    # whole-word matching still applies to the added keywords
    text = "Assisted the audit team.\nSupervised weekend shifts.\nAdvisory board member."
    assert extract_titles(text) == []
