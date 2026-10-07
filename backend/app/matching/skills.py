"""Skill normalisation and the built-in skill ontology.

* ``skill_key`` collapses spelling variants ("Node.js", "NodeJS", "node js") to one *loose key*; it is the
  unique identity of a skill and of its aliases.
* ``ONTOLOGY`` is the starter taxonomy (canonical name, category, family, aliases). Skills in the same
  *family* are related (MySQL ↔ PostgreSQL, React ↔ Vue) and earn partial credit in matching. Admins/users can
  add more skills at runtime; the ontology only seeds the table and drives résumé skill extraction.

Line format: ``Name | Category | family | alias, alias, ... | flags`` where flag ``~`` marks an *ambiguous* term
(common English word / one letter) that the résumé extractor only accepts in a skills-like context.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_STRIP = re.compile(r"[\s\-_./()\\,;:]+")


def skill_key(text: str) -> str:
    """Loose, comparison-safe key. Keeps ``+`` and ``#`` so C, C++ and C# stay distinct."""
    t = unicodedata.normalize("NFKC", text).casefold().strip()
    t = t.replace("&", "and")
    return _STRIP.sub("", t)


@dataclass(frozen=True, slots=True)
class OntologySkill:
    name: str
    category: str
    family: str | None
    aliases: tuple[str, ...]
    ambiguous: bool = False

    @property
    def key(self) -> str:
        return skill_key(self.name)


_RAW = """
# --- Programming languages -------------------------------------------------------------------
Python | Programming Languages | | python3, py
Java | Programming Languages | jvm-language | java se, java ee, j2ee
Kotlin | Programming Languages | jvm-language |
Scala | Programming Languages | jvm-language |
JavaScript | Programming Languages | javascript-language | js, ecmascript, es6
TypeScript | Programming Languages | javascript-language | ts
Go | Programming Languages | | golang | ~
Rust | Programming Languages | | rustlang | ~
C | Programming Languages | | c language | ~
C++ | Programming Languages | | cpp
C# | Programming Languages | dotnet | csharp, c sharp
Ruby | Programming Languages | | ruby lang | ~
PHP | Programming Languages | |
Swift | Programming Languages | | swift lang | ~
Objective-C | Programming Languages | |
R | Programming Languages | | r language, rstats | ~
SQL | Programming Languages | | structured query language
Bash | Programming Languages | | shell scripting, shell, sh
PowerShell | Programming Languages | |
Dart | Programming Languages | |
Elixir | Programming Languages | |
Haskell | Programming Languages | |
MATLAB | Programming Languages | |
# --- Backend frameworks ----------------------------------------------------------------------
FastAPI | Backend Frameworks | python-web-framework | fast api
Django | Backend Frameworks | python-web-framework | django rest framework, drf
Flask | Backend Frameworks | python-web-framework | | ~
Node.js | Backend Frameworks | | node, nodejs, node js
Express | Backend Frameworks | node-web-framework | express.js, expressjs | ~
NestJS | Backend Frameworks | node-web-framework | nest.js, nest js
Spring Boot | Backend Frameworks | java-web-framework | spring, spring framework
ASP.NET | Backend Frameworks | dotnet | asp.net core, aspnet
.NET | Backend Frameworks | dotnet | dotnet core, .net core
Ruby on Rails | Backend Frameworks | | rails, ror
Laravel | Backend Frameworks | |
GraphQL | Backend Frameworks | api-style | graph ql
REST APIs | Backend Frameworks | api-style | rest, restful, restful apis, rest api, restful api
gRPC | Backend Frameworks | api-style |
Microservices | Backend Frameworks | | micro services, microservice architecture
Celery | Backend Frameworks | task-queue | celery workers
SQLAlchemy | Backend Frameworks | python-orm | sql alchemy
Pydantic | Backend Frameworks | |
# --- Frontend --------------------------------------------------------------------------------
React | Frontend | frontend-framework | reactjs, react.js, react js
Next.js | Frontend | react-meta-framework | nextjs, next js
Vue | Frontend | frontend-framework | vue.js, vuejs, vue js
Nuxt | Frontend | | nuxt.js, nuxtjs
Angular | Frontend | frontend-framework | angularjs, angular.js
Svelte | Frontend | frontend-framework | sveltekit
Redux | Frontend | | redux toolkit
HTML | Frontend | | html5
CSS | Frontend | | css3
Sass | Frontend | | scss
Tailwind CSS | Frontend | css-framework | tailwind, tailwindcss
Bootstrap | Frontend | css-framework |
Material UI | Frontend | css-framework | mui, material-ui
Webpack | Frontend | | 
Vite | Frontend | |
React Native | Mobile | mobile-cross-platform | react-native
Flutter | Mobile | mobile-cross-platform |
Android | Mobile | mobile-native | android development, android sdk
iOS | Mobile | mobile-native | ios development, ios sdk
# --- Databases -------------------------------------------------------------------------------
PostgreSQL | Databases | relational-database | postgres, psql, postgre sql
MySQL | Databases | relational-database |
MariaDB | Databases | relational-database |
SQL Server | Databases | relational-database | mssql, microsoft sql server, ms sql
Oracle Database | Databases | relational-database | oracle db, oracle sql, pl/sql
SQLite | Databases | relational-database |
MongoDB | Databases | nosql-database | mongo
Cassandra | Databases | nosql-database | apache cassandra
DynamoDB | Databases | nosql-database | dynamo db
Elasticsearch | Databases | search-engine | elastic search, elk
OpenSearch | Databases | search-engine |
Redis | Databases | cache-store |
Memcached | Databases | cache-store |
Snowflake | Databases | data-warehouse |
BigQuery | Databases | data-warehouse | big query
Redshift | Databases | data-warehouse | amazon redshift
pgvector | Databases | vector-database | pg vector
Pinecone | Databases | vector-database |
Database Design | Databases | | data modeling, schema design, database modeling
Query Optimization | Databases | | sql tuning, query tuning, performance tuning
# --- Cloud & DevOps --------------------------------------------------------------------------
AWS | Cloud & DevOps | cloud-platform | amazon web services, ec2, s3
Azure | Cloud & DevOps | cloud-platform | microsoft azure
GCP | Cloud & DevOps | cloud-platform | google cloud, google cloud platform
Docker | Cloud & DevOps | containers | docker compose, dockerfile, containerization
Kubernetes | Cloud & DevOps | container-orchestration | k8s, kube, helm
OpenShift | Cloud & DevOps | container-orchestration |
Terraform | Cloud & DevOps | infrastructure-as-code | iac
Ansible | Cloud & DevOps | infrastructure-as-code |
Pulumi | Cloud & DevOps | infrastructure-as-code |
CloudFormation | Cloud & DevOps | infrastructure-as-code | aws cloudformation
CI/CD | Cloud & DevOps | | cicd, continuous integration, continuous delivery, continuous deployment
GitHub Actions | Cloud & DevOps | ci-cd-tool | github action
GitLab CI | Cloud & DevOps | ci-cd-tool | gitlab ci/cd, gitlab pipelines
Jenkins | Cloud & DevOps | ci-cd-tool |
CircleCI | Cloud & DevOps | ci-cd-tool | circle ci
Git | Cloud & DevOps | | github, gitlab, version control
Linux | Cloud & DevOps | | unix, ubuntu
Nginx | Cloud & DevOps | web-server | nginx
Prometheus | Cloud & DevOps | observability |
Grafana | Cloud & DevOps | observability |
Datadog | Cloud & DevOps | observability |
Monitoring | Cloud & DevOps | | observability, logging and monitoring
Serverless | Cloud & DevOps | | aws lambda, lambda, cloud functions
Site Reliability | Cloud & DevOps | | sre, site reliability engineering
# --- Messaging & data engineering ------------------------------------------------------------
Kafka | Data Engineering | message-queue | apache kafka
RabbitMQ | Data Engineering | message-queue | rabbit mq
Amazon SQS | Data Engineering | message-queue | sqs
Apache Spark | Data Engineering | big-data-processing | spark, pyspark | ~
Hadoop | Data Engineering | big-data-processing |
Apache Flink | Data Engineering | big-data-processing | flink
Airflow | Data Engineering | workflow-orchestration | apache airflow
dbt | Data Engineering | | data build tool
ETL | Data Engineering | | elt, data pipelines, data pipeline
Data Warehousing | Data Engineering | | data warehouse
# --- Data science & ML -----------------------------------------------------------------------
Machine Learning | Data Science & AI | | ml, machine-learning
Deep Learning | Data Science & AI | | neural networks
Natural Language Processing | Data Science & AI | | nlp
Computer Vision | Data Science & AI | |
Large Language Models | Data Science & AI | | llm, llms, generative ai, genai
Semantic Search | Data Science & AI | | vector search, embeddings, text embeddings, sentence embeddings
PyTorch | Data Science & AI | deep-learning-framework | torch
TensorFlow | Data Science & AI | deep-learning-framework | tf
Keras | Data Science & AI | deep-learning-framework |
scikit-learn | Data Science & AI | ml-library | sklearn, scikit learn
Hugging Face | Data Science & AI | ml-library | huggingface, transformers
Pandas | Data Science & AI | data-analysis-library |
NumPy | Data Science & AI | data-analysis-library |
Statistics | Data Science & AI | | statistical analysis, statistical modeling
A/B Testing | Data Science & AI | | ab testing, experimentation
Data Analysis | Data Science & AI | | data analytics, analytics
Tableau | Data Science & AI | bi-tool |
Power BI | Data Science & AI | bi-tool | powerbi
Looker | Data Science & AI | bi-tool |
MLOps | Data Science & AI | | ml ops
# --- Testing & practices ---------------------------------------------------------------------
Pytest | Testing | python-testing | py.test
Jest | Testing | js-testing |
Cypress | Testing | e2e-testing |
Playwright | Testing | e2e-testing |
Selenium | Testing | e2e-testing |
JUnit | Testing | java-testing |
Unit Testing | Testing | | unit tests, tdd, test-driven development
Test Automation | Testing | | automated testing, qa automation
Agile | Practices | | agile methodologies
Scrum | Practices | |
Kanban | Practices | |
Code Review | Practices | | code reviews
System Design | Practices | | software architecture, distributed systems, solution architecture
Security | Practices | | application security, appsec, cybersecurity, owasp
OAuth | Practices | | oauth2, openid connect, oidc, jwt
# --- Design & product ------------------------------------------------------------------------
Figma | Design | design-tool |
Adobe XD | Design | design-tool |
Sketch | Design | design-tool | | ~
Photoshop | Design | adobe-creative | adobe photoshop
Illustrator | Design | adobe-creative | adobe illustrator
UX Design | Design | | user experience, ux, ui/ux, ui ux
UI Design | Design | | user interface design
User Research | Design | | ux research
Prototyping | Design | | wireframing, wireframes
Product Management | Product | | product manager
Roadmapping | Product | | product roadmap
Jira | Product | project-tool |
Confluence | Product | project-tool |
Asana | Product | project-tool |
# --- Marketing -------------------------------------------------------------------------------
SEO | Marketing | | search engine optimization
SEM | Marketing | | google ads, ppc, paid search
Content Marketing | Marketing | |
Social Media Marketing | Marketing | | social media
Email Marketing | Marketing | | mailchimp
Google Analytics | Marketing | web-analytics | ga4
Brand Management | Marketing | | branding
Copywriting | Marketing | | copy writing
Marketing Automation | Marketing | | hubspot
# --- Sales & customer ------------------------------------------------------------------------
Salesforce | Sales | crm | sfdc
CRM | Sales | crm | customer relationship management
B2B Sales | Sales | | enterprise sales
Negotiation | Sales | |
Lead Generation | Sales | | prospecting
Account Management | Sales | | key account management
Customer Support | Customer Success | | customer service
Customer Success | Customer Success | |
# --- Finance & operations --------------------------------------------------------------------
Financial Analysis | Finance | | financial modeling, fp&a
Accounting | Finance | | bookkeeping
Excel | Finance | office-suite | microsoft excel, ms excel | ~
QuickBooks | Finance | accounting-software |
SAP | Finance | erp | sap erp
Budgeting | Finance | | budget management, forecasting
Auditing | Finance | | internal audit
Supply Chain | Operations | | logistics, procurement
Project Management | Operations | | pmp, project planning
Process Improvement | Operations | | lean, six sigma
# --- People ----------------------------------------------------------------------------------
Recruiting | Human Resources | | talent acquisition, sourcing
Payroll | Human Resources | |
Employee Relations | Human Resources | | hr
# --- Healthcare ------------------------------------------------------------------------------
Patient Care | Healthcare | | patient assessment
Critical Care | Healthcare | | icu, intensive care, intensive care unit
BLS | Healthcare | | basic life support
ACLS | Healthcare | | advanced cardiac life support
Medication Administration | Healthcare | |
Electronic Health Records | Healthcare | | ehr, emr, epic
Clinical Documentation | Healthcare | |
# --- Professional ----------------------------------------------------------------------------
Leadership | Professional | | team leadership, people management
Mentoring | Professional | | coaching
Technical Writing | Professional | | documentation
Public Speaking | Professional | | presentations
"""


def _parse() -> tuple[OntologySkill, ...]:
    skills: list[OntologySkill] = []
    for raw in _RAW.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        parts += [""] * (5 - len(parts))
        name, category, family, aliases, flags = parts[:5]
        skills.append(
            OntologySkill(
                name=name,
                category=category,
                family=family or None,
                aliases=tuple(a.strip() for a in aliases.split(",") if a.strip()),
                ambiguous="~" in flags or "~" in aliases,
            )
        )
    # Stripping a trailing "~" that landed in the alias column (when the family/alias columns are empty).
    cleaned = []
    for s in skills:
        aliases = tuple(a.rstrip(" ~") for a in s.aliases if a.strip("~ "))
        cleaned.append(OntologySkill(s.name, s.category, s.family, aliases, s.ambiguous))
    return tuple(cleaned)


ONTOLOGY: tuple[OntologySkill, ...] = _parse()


def _check_unique() -> None:
    seen: dict[str, str] = {}
    for s in ONTOLOGY:
        for term in (s.name, *s.aliases):
            k = skill_key(term)
            if k in seen and seen[k] != s.name:
                raise ValueError(f"ontology key collision: {term!r} ({s.name}) vs {seen[k]}")
            seen[k] = s.name


_check_unique()
