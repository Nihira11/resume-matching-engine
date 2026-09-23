"""
Curated tools and methods that ESCO doesn't cover, or maps wrongly.

ESCO is a general-workforce taxonomy updated every few years. Scoring 13
real data/AI/analyst postings showed it has no entry at all for most of
what those postings screen on -- Tableau, Power BI, pandas, PyTorch,
LLMs, RAG, AWS, Jira -- and maps a few others to the wrong concept
(TensorFlow -> "computer vision", Confluence -> "use online tools to
collaborate"). A skill the matcher can't see can't show up as matched or
missing, so the gap analysis silently skipped the requirements that
matter most for these roles.

Loaded into skills_taxonomy with source='curated' by
scripts/load_tech_skills.py. SkillMatcher gives curated terms precedence
over ESCO for the same surface form.

Each entry is (skill_name, category, aliases). Names already canonical in
ESCO (Python via "Python (computer programming)", SQL, R, Java, C++,
TypeScript, PostgreSQL, MySQL, Hadoop, Microsoft Visio, machine learning,
deep learning, natural language processing, fraud detection, customer
segmentation, business process modelling) are deliberately left out -- ESCO already handles
them correctly.
"""
from __future__ import annotations

TECH_SKILLS: list[tuple[str, str, list[str]]] = [
    # BI, reporting and analytics tools
    ("Tableau", "tool", []),
    ("Power BI", "tool", ["PowerBI", "Microsoft Power BI"]),
    ("Looker", "tool", ["Looker Studio"]),
    ("Qlik", "tool", ["Qlik Sense", "QlikView"]),
    ("Amazon QuickSight", "tool", ["QuickSight", "Quicksight"]),
    ("Microsoft Excel", "tool", ["Excel", "MS Excel", "Advanced Excel"]),
    ("DAX", "tool", []),
    ("Alteryx", "tool", []),
    ("Microsoft Office", "tool", ["MS Office", "Office 365", "Microsoft 365"]),
    ("Microsoft PowerPoint", "tool", ["PowerPoint"]),
    ("Jupyter", "tool", ["Jupyter Notebook", "JupyterLab"]),
    ("Streamlit", "tool", []),
    ("R Shiny", "tool", ["Shiny"]),
    ("Plotly", "tool", ["Plotly Dash"]),
    ("seaborn", "tool", ["Seaborn"]),
    ("matplotlib", "tool", ["Matplotlib"]),
    ("ggplot2", "tool", []),
    ("tidyverse", "tool", ["dplyr", "tidyquant"]),
    ("data visualisation", "technical", ["data visualization", "data viz"]),
    ("dashboard development", "technical", ["dashboards", "dashboarding", "KPI dashboards"]),

    # data engineering and platforms
    ("Apache Spark", "tool", ["PySpark", "Spark SQL", "Spark"]),
    ("Databricks", "tool", []),
    ("Snowflake", "tool", []),
    ("dbt", "tool", ["data build tool"]),
    ("Apache Airflow", "tool", ["Airflow"]),
    ("Apache Kafka", "tool", ["Kafka"]),
    ("Metaflow", "tool", []),
    ("Google BigQuery", "tool", ["BigQuery"]),
    ("Amazon Redshift", "tool", ["Redshift"]),
    ("MongoDB", "tool", []),
    ("pgvector", "tool", []),
    ("ETL", "technical", ["ELT", "data pipelines", "data pipeline", "ETL pipelines"]),
    ("data quality", "technical", ["data integrity", "data validation"]),
    ("data governance", "technical", []),
    ("data modelling", "technical", ["data modeling", "dimensional modelling"]),

    # Python data and ML libraries
    ("pandas", "tool", ["Pandas"]),
    ("NumPy", "tool", ["numpy"]),
    ("SciPy", "tool", ["scipy"]),
    ("scikit-learn", "tool", ["sklearn", "scikit learn"]),
    ("statsmodels", "tool", []),
    ("PyTorch", "tool", ["pytorch", "Torch"]),
    ("TensorFlow", "tool", ["Tensorflow", "tensorflow"]),
    ("Keras", "tool", []),
    ("JAX", "tool", []),
    ("XGBoost", "tool", ["xgboost"]),
    ("LightGBM", "tool", []),
    ("CatBoost", "tool", []),
    ("SHAP", "tool", ["SHAP values"]),
    ("Hugging Face", "tool", ["Hugging Face Transformers", "HuggingFace"]),
    ("sentence-transformers", "tool", ["sentence transformers"]),
    ("spaCy", "tool", ["spacy"]),
    ("NLTK", "tool", []),
    ("LangChain", "tool", []),
    ("LlamaIndex", "tool", []),
    ("OpenCV", "tool", []),

    # AI / LLM methods
    ("large language models", "technical", ["LLM", "LLMs", "large language model"]),
    ("retrieval-augmented generation", "technical", ["RAG", "retrieval augmented generation", "advanced RAG"]),
    ("prompt engineering", "technical", ["prompting", "prompt design"]),
    ("LLM fine-tuning", "technical", ["fine-tuning", "fine tuning", "fine-tuning LLMs"]),
    ("agentic AI", "technical", ["agentic workflows", "AI agents", "agentic use cases", "Agentic AI"]),
    ("generative AI", "technical", ["GenAI", "Gen AI", "Generative AI"]),
    ("LLM evaluation", "technical", ["evaluation systems", "evals", "AI evaluation"]),
    ("BERT", "technical", []),
    ("MLOps", "technical", ["model deployment", "model monitoring"]),

    # statistics and modelling methods
    ("statistical modelling", "technical", ["statistical modeling", "statistical models", "statistical modeling techniques"]),
    ("predictive modelling", "technical", ["predictive modeling", "predictive models", "predictive analytics"]),
    ("time series analysis", "technical", ["time-series analysis", "time series forecasting", "time-series", "time series"]),
    ("forecasting", "technical", ["nowcasting", "business forecasting"]),
    ("econometrics", "technical", ["econometric models", "econometric"]),
    ("A/B testing", "technical", ["A/B tests", "AB testing", "split testing"]),
    ("experimental design", "technical", ["design of experiments", "experimentation"]),
    ("hypothesis testing", "technical", ["statistical testing", "significance testing"]),
    ("Bayesian inference", "technical", ["Bayesian statistics", "Bayesian"]),
    ("regression analysis", "technical", ["linear regression", "logistic regression"]),
    ("random forest", "technical", ["random forests", "Random Forest"]),
    ("gradient boosting", "technical", ["gradient boosted trees", "GBM"]),
    ("clustering", "technical", ["K-Means", "k-means clustering"]),
    ("feature engineering", "technical", []),
    ("model validation", "technical", ["model evaluation", "cross-validation", "backtesting"]),
    ("anomaly detection", "technical", ["outlier detection"]),
    ("sequence modelling", "technical", ["sequence modeling"]),

    # cloud, engineering and delivery tooling
    ("Amazon Web Services", "tool", ["AWS"]),
    ("Microsoft Azure", "tool", ["Azure"]),
    ("Azure Machine Learning", "tool", ["Azure ML"]),
    ("Google Cloud Platform", "tool", ["GCP", "Google Cloud"]),
    ("Amazon SageMaker", "tool", ["SageMaker"]),
    ("Docker", "tool", []),
    ("Kubernetes", "tool", ["k8s"]),
    ("Git", "tool", ["git", "GitHub", "GitLab"]),
    ("version control", "technical", ["source control"]),
    ("CI/CD", "technical", ["continuous integration", "continuous deployment", "continuous delivery"]),
    ("REST APIs", "technical", ["REST API", "RESTful APIs", "APIs"]),
    ("unit testing", "technical", ["unit tests", "test automation"]),
    ("React", "tool", ["React.js", "ReactJS"]),
    ("Node.js", "tool", ["NodeJS", "Node"]),
    ("full-stack development", "technical", ["full-stack", "full stack development"]),
    ("Android development", "technical", ["Android"]),
    ("VBA", "tool", []),

    # business analysis and delivery
    ("Jira", "tool", ["JIRA"]),
    ("Confluence", "tool", []),
    ("Scrum", "technical", ["Scrum framework"]),
    ("Kanban", "technical", []),
    ("user stories", "technical", ["user story", "story mapping"]),
    ("acceptance criteria", "technical", []),
    ("backlog management", "technical", ["backlog refinement", "product backlog", "product backlogs", "backlogs"]),
    ("requirements gathering", "technical", ["requirements elicitation", "gathering requirements", "gather requirements", "requirements discovery"]),
    ("stakeholder management", "soft", ["stakeholder engagement", "stakeholder engagements"]),
    ("process mapping", "technical", ["process maps", "current state processes", "future state processes"]),
    ("user acceptance testing", "technical", ["UAT"]),
    ("software development lifecycle", "technical", ["SDLC", "software development life cycle"]),
    ("ServiceNow", "tool", []),
    ("Workday", "tool", []),
    ("benefits realisation", "technical", ["benefits realization"]),
    ("KPI reporting", "technical", ["KPIs", "key performance indicators", "performance metrics"]),

    # quantitative finance
    ("derivatives", "technical", ["OTC derivatives", "listed derivatives"]),
    ("options pricing", "technical", ["options theory", "option pricing"]),
    ("fixed income", "technical", []),
    ("foreign exchange", "technical", ["FX trading"]),
    ("market making", "technical", ["market-making"]),
    ("value at risk", "technical", ["VaR", "CVaR", "expected shortfall"]),
    ("GARCH", "technical", ["GARCH models", "eGARCH", "sGARCH"]),
    ("volatility modelling", "technical", ["volatility forecasting", "volatility modeling"]),
    ("credit risk modelling", "technical", ["credit risk", "credit scorecard", "credit scoring"]),
    ("quantitative finance", "technical", ["quantitative trading"]),
]

# Surface forms that are also ordinary English words or common
# capitalised words. Matched case-sensitively, exactly as written here:
# "React" is the library, "react quickly to issues" is not; "Excel" is
# the tool, "excel in a team" is not. Every other curated term matches
# case-insensitively, like ESCO.
CASE_SENSITIVE_TERMS: frozenset[str] = frozenset({
    "Excel", "Spark", "Shiny", "React", "Node", "Looker", "Snowflake",
    "Airflow", "Confluence", "Workday", "Torch", "Azure", "RAG", "VaR",
    "BERT",
})
