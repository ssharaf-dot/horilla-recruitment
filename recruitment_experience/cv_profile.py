"""Bounded, local PDF text extraction. Suggestions only, no model or network calls."""
import hashlib
import re
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

HEADINGS = {
    'about': {'profile','summary','professional summary','about me','career summary','personal statement'},
    'experience': {'experience','work experience','professional experience','employment history','career history','employment'},
    'education': {'education','qualifications','academic qualifications','academic background'},
    'skills': {'skills','key skills','technical skills','core competencies','areas of expertise'},
}
LIMITS = {'about':4000,'experience':6000,'education':4000,'skills':2000}


def suggest_from_text(text):
    lines=[line.strip() for line in text[:50000].splitlines() if line.strip()]
    suggestions={}
    emails=re.findall(r'(?<![A-Z0-9.!#$%&\x27*+/=?^_`{|}~-])[A-Z0-9.!#$%&\x27*+/=?^_`{|}~-]{1,64}@[A-Z0-9-]{1,63}(?:\.[A-Z0-9-]{1,63}){1,10}(?![A-Z0-9.-])',text,re.I)
    for value in emails:
        try:validate_email(value)
        except ValidationError:continue
        suggestions['email']=value[:254];break
    for line in lines[:18]:
        match=re.match(r'^(?:name|full name)\s*:\s*(.+)$',line,re.I)
        if match and len(match[1])<=100:
            suggestions['name']=match[1];break
    # Only explicit contact-labelled numbers; dates, IDs and years are not phones.
    for line in lines:
        if re.match(r'^(?:mobile|phone|telephone|tel|contact)\s*[:+]',line,re.I):
            number=re.search(r'(\+?\d[\d ()-]{7,22}\d)',line)
            if number:
                value=re.sub(r'[ ()-]','',number[1])
                if 8<=len(value.lstrip('+'))<=15 and len(value)<=15:suggestions['mobile']=value;break
    current=None;sections={key:[] for key in HEADINGS}
    for line in lines:
        label=line.rstrip(':').strip().casefold()
        found=next((key for key,names in HEADINGS.items() if label in names),None)
        if found:current=found;continue
        # A recognised unrelated heading terminates the previous section.
        if label in {'references','personal details','interests','hobbies','languages','certifications','awards','contact details'}:
            current=None
        elif current:sections[current].append(line)
    for key,values in sections.items():
        if values:suggestions[key]='\n'.join(values)[:LIMITS[key]]
    return suggestions


def extract_resume(candidate):
    if not candidate.resume:return {},'', 'No CV has been uploaded. Enter the profile manually.'
    try:
        with candidate.resume.open('rb') as source:
            raw=source.read(10*1024*1024+1)
        if len(raw)>10*1024*1024:return {},'', 'This CV exceeds the 10 MB extraction limit. Enter the profile manually.'
        import fitz
        with fitz.open(stream=raw,filetype='pdf') as document:
            if document.is_encrypted:return {},'', 'This PDF is password protected. Enter the profile manually.'
            text='\n'.join(document[i].get_text()[:12000] for i in range(min(document.page_count,20)))[:50000]
        if not text.strip():return {},'', 'No readable text was found. This may be a scanned CV; enter the profile manually.'
        suggestions=suggest_from_text(text)
        note='Suggestions use readable text from up to 20 PDF pages. Layouts vary; check every field against the CV.'
        if not suggestions:note='No recognised contact labels or section headings were found. Enter the profile manually.'
        return suggestions,hashlib.sha256(raw).hexdigest(),note
    except (FileNotFoundError,OSError,RuntimeError,ValueError):
        return {},'', 'The CV could not be read. The original file is unchanged; enter the profile manually.'
