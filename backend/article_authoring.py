"""PubMed-verified daily anesthesiology article + OpenAI journal-club takeaway.

Never trust model-generated citations: article identifiers, titles, DOI, authors
and URLs are always taken from PubMed metadata, not OpenAI output.
"""
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
import httpx

from .openai_authoring import MODEL, ENDPOINT

LOG = logging.getLogger("ite.article")

# Selected landmark guidelines and influential perioperative papers, PMID-verified.
LANDMARK_PMIDS = (
    "34762729",  # ASA difficult airway (2022)
    "36520073",  # ASA quantitative neuromuscular blockade guidelines (2023)
    "39316661",  # AHA/ACC perioperative cardiovascular guideline (2024)
    "41203471",  # DAS difficult airway guideline (2025 / 2026)
    "41237407",  # Fifth PONV consensus guideline (2026)
    "36629465",  # ASA preoperative fasting (2023)
    "32467512",  # Fourth PONV consensus (2020)
    "28806470",  # Sugammadex versus neostigmine systematic review
    "32405975",  # Sugammadex versus neostigmine RCT
    "29742967",  # RELAX restrictive versus liberal fluid therapy
)
SEARCHES = (
    '(anesthesia[Title] OR anesthesiology[Title] OR perioperative[Title]) AND (guideline[Title] OR consensus[Title]) AND 2019:2026[dp]',
    '(anesthesia[Title] OR perioperative[Title]) AND randomized controlled trial[Publication Type] AND 2018:2026[dp]',
    '(airway[Title] OR intubation[Title]) AND (practice guideline[Publication Type] OR systematic review[Publication Type]) AND 2018:2026[dp]',
    '(neuromuscular blockade[Title] OR regional anesthesia[Title]) AND (guideline[Title] OR systematic review[Publication Type]) AND 2018:2026[dp]',
    '(postoperative complications[Title] OR hypotension[Title]) AND (anesthesia[Title] OR perioperative[Title]) AND 2018:2026[dp]',
    '(obstetric anesthesia[Title] OR pediatric anesthesia[Title]) AND (guideline[Title] OR systematic review[Publication Type]) AND 2018:2026[dp]',
)
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


def clean_text(element):
    return " ".join(" ".join(element.itertext()).split()) if element is not None else ""


def parse_articles(xml):
    out = []
    root = ET.fromstring(xml)
    for record in root.findall(".//PubmedArticle"):
        citation = record.find("MedlineCitation")
        article = citation.find("Article") if citation is not None else None
        if article is None:
            continue
        pmid = (citation.findtext("PMID") or "").strip()
        title = clean_text(article.find("ArticleTitle"))
        journal = clean_text(article.find("./Journal/Title"))
        abstract = " ".join(clean_text(x) for x in article.findall("./Abstract/AbstractText"))
        doi = ""
        for identifier in record.findall("./PubmedData/ArticleIdList/ArticleId"):
            if identifier.get("IdType") == "doi":
                doi = clean_text(identifier).strip()
                break
        pubdate = article.find("./Journal/JournalIssue/PubDate")
        year = (pubdate.findtext("Year") if pubdate is not None else "") or ""
        if not year and pubdate is not None:
            match = re.search(r"(19|20)\d{2}", clean_text(pubdate))
            year = match.group() if match else ""
        authors = []
        for author in article.findall("./AuthorList/Author")[:3]:
            last = author.findtext("LastName") or author.findtext("CollectiveName")
            initials = author.findtext("Initials") or ""
            if last:
                authors.append((initials + " " + last).strip())
        if pmid and title and journal and abstract and 2015 <= int(year or 0) <= __import__("datetime").date.today().year:
            out.append({
                "pmid": pmid, "title": title, "journal": journal,
                "year": year, "authors": ", ".join(authors) + (" et al." if len(authors) >= 3 else ""),
                "doi": doi, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "abstract": abstract[:2600],
            })
    return out


async def pubmed_candidates(client, *, date_string, existing):
    # Batch-verify real PubMed IDs; supplement the catalog with new indexed papers
    # as its read history fills up. No unverified generative citations are allowed.
    pmids = list(LANDMARK_PMIDS)
    used = {str(a.get("doi") or "").lower() for a in existing}
    used_urls = {str(a.get("url") or "") for a in existing}
    seen_titles = {str(a.get("title") or "").casefold() for a in existing}
    async def fetch(ids):
        response = await client.get(EUTILS + "efetch.fcgi", params={
            "db": "pubmed", "id": ",".join(ids), "retmode": "xml"
        })
        response.raise_for_status()
        return parse_articles(response.text)

    candidates = await fetch(pmids)
    remaining = lambda paper: (
        paper["url"] not in used_urls and paper["title"].casefold() not in seen_titles
        and (not paper["doi"] or paper["doi"].lower() not in used)
    )
    fresh = [p for p in candidates if remaining(p)]
    if len(fresh) < 4:
        from datetime import date
        bucket = date.fromisoformat(date_string).toordinal() % len(SEARCHES)
        search = await client.get(EUTILS + "esearch.fcgi", params={
            "db": "pubmed", "term": SEARCHES[bucket].replace("2026[dp]", f"{date.fromisoformat(date_string).year}[dp]"), "retmax": 18,
            "retmode": "json", "sort": "relevance",
        })
        search.raise_for_status()
        found = search.json().get("esearchresult", {}).get("idlist", [])
        if found:
            extra = await fetch(found)
            fresh.extend(p for p in extra if remaining(p) and p["pmid"] not in {x["pmid"] for x in fresh})
    return fresh[:12]


async def prepare_daily_article(db, *, today):
    """Choose real PubMed metadata and have OpenAI produce a grounded reading note."""
    existing = await db.all("SELECT title,doi,url,date,topic FROM study_articles ORDER BY date DESC LIMIT 500")
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0),
                                 headers={"User-Agent": "AnesthesiaITEStudy/1.0 (educational)"}) as client:
        options = await pubmed_candidates(client, date_string=today, existing=existing)
    if not options:
        raise RuntimeError("No new PubMed-verified must-read anesthesia article found")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    evidence = [
        {"pmid": p["pmid"], "title": p["title"], "year": p["year"],
         "journal": p["journal"], "abstract": p["abstract"]}
        for p in options
    ]
    prompt = json.dumps({
        "task": "Select ONE high-impact must-read anesthesia article from verified PubMed candidates and write a concise evidence-grounded reading note.",
        "criteria": "Prioritize widely relevant practice-changing guidelines, seminal trials, and strong evidence. Rotate subspecialties and avoid the last 3 articles' clinical topics. Avoid selecting superseded guidelines when a newer edition appears. Do not invent numerical results or recommendations not in the supplied abstracts.",
        "recently_read_articles": [
            {"title": a["title"], "topic": a.get("topic")} for a in existing[:10]
        ],
        "candidates": evidence,
        "output": {"pmid": "copy one candidate PMID", "topic": "short clinical subject",
                   "takeaway": "3-4 sentences: why every anesthesiologist should read it, high-yield message and one limitation. Acknowledge if full text was not assessed."}
    }, ensure_ascii=False)
    payload = {
        "model": MODEL,
        "instructions": "You are an anesthesiology journal club editor. Return only a JSON object. Choose one provided PMID; do not invent literature, DOI, links, authors or results. Base the takeaway strictly on the supplied PubMed abstract and label it as abstract-based.",
        "input": "Return a JSON object only.\n" + prompt,
        "max_output_tokens": 650,
        "text": {"format": {"type": "json_object"}}
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0)) as client:
        response = await client.post(ENDPOINT, headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
        }, json=payload)
        response.raise_for_status()
        data = response.json()
    if data.get("status") != "completed":
        raise RuntimeError("OpenAI article note not completed")
    output = "".join(item.get("text", "") for part in data.get("output", [])
                     for item in part.get("content", []) if item.get("type") == "output_text")
    picked = json.loads(output)
    chosen = next((p for p in options if p["pmid"] == str(picked.get("pmid"))), None)
    if chosen is None:
        raise ValueError("OpenAI selected a PMID absent from verified candidates")
    takeaway = str(picked.get("takeaway") or "").strip()
    if len(takeaway) < 75 or len(takeaway) > 1800:
        raise ValueError("OpenAI article takeaway is missing or too long")
    topic = str(picked.get("topic") or "").strip()[:200] or "High-yield anesthesiology"
    return {
        "date": today, "title": chosen["title"],
        "url": chosen["url"], "doi": chosen["doi"], "year": chosen["year"],
        "authors": chosen["authors"], "journal": chosen["journal"],
        "topic": topic, "takeaway": takeaway, "status": "Prepared",
    }
