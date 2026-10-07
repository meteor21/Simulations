"""Optional permitted RSS/Atom collection for prospective, in-office monitoring."""
from __future__ import annotations
import email.utils
import json
import re
from datetime import timezone
from defusedxml import ElementTree as ET
from .annotate import name_pattern
from .scrape import Scraper
from .util import iso,now,allowed_host


def parse_feed(xml_bytes):
    root=ET.fromstring(xml_bytes); rows=[]
    entries=root.findall('.//item') or root.findall('{http://www.w3.org/2005/Atom}entry')
    for item in entries:
        def text(*tags):
            for tag in tags:
                node=item.find(tag)
                if node is not None and node.text: return node.text.strip()
            return ''
        title=text('title','{http://www.w3.org/2005/Atom}title')
        url=text('link')
        if not url:
            for link in item.findall('{http://www.w3.org/2005/Atom}link'):
                if link.get('rel','alternate')=='alternate': url=link.get('href',''); break
        rawdate=text('pubDate','{http://www.w3.org/2005/Atom}published','{http://purl.org/dc/elements/1.1/}date')
        published=None
        if rawdate:
            try: published=iso(rawdate)
            except (ValueError,TypeError):
                try:
                    parsed=email.utils.parsedate_to_datetime(rawdate)
                    if parsed.tzinfo is not None: published=iso(parsed)
                except (ValueError,TypeError): pass
        # An Atom updated date is NOT silently substituted for a publication date.
        summary=text('description','{http://www.w3.org/2005/Atom}summary')
        summary=re.sub('<[^>]+>',' ',summary)
        if title and url: rows.append({'url':url,'title':title,'published_at':published,'summary':summary})
    return rows


def collect_feed(store,client,feed_url,candidate_ids,*,allowed_domains,rights_note,max_items=100):
    if not rights_note: raise ValueError('Record the permission/terms basis for this feed')
    if type(max_items) is not int or max_items<0: raise ValueError('max_items must be a nonnegative integer')
    requested=set(candidate_ids)
    candidates={r['candidate_id']:json.loads(r['aliases_json']) for r in store.rows('SELECT * FROM cs_candidates') if r['candidate_id'] in requested}
    if not requested or set(candidates)!=requested: raise ValueError('Select existing candidate IDs for feed discovery')
    if max_items==0: return {'matched_items':0,'coverage':'Feed disabled by zero item limit; no requests made'}
    guard=Scraper(client,allowed_domains)
    interval=guard.allowed(feed_url)
    response=client.get(feed_url,min_interval=interval,max_bytes=2_000_000)
    if response.status_code!=200: raise ValueError('Feed did not return 200; no redirect/access bypass attempted')
    count=0
    for row in parse_feed(response.content)[:max_items]:
        if not allowed_host(row['url'],allowed_domains): continue
        text=row['title']+'\n'+row['summary']
        matched=[cid for cid,aliases in candidates.items() if any(re.search(name_pattern(a),text,re.I) for a in aliases)]
        if not matched: continue
        store.article(url=row['url'],title=row['title'],body='',candidate_ids=matched,
             published_at=row['published_at'],retrieved_at=now(),rights_note=rights_note,
             metadata={'provider':'publisher_rss','summary_used_for_discovery_only':True,
                       'summary_only_match_possible':not any(re.search(name_pattern(a),row['title'],re.I) for cid in matched for a in candidates[cid]),
                       'feed_url':feed_url,'date_is_feed_claim':True})
        count+=1
    store.con.commit(); store.event('CollectionAgent','rss_collect',feed_url=feed_url,matched_items=count)
    return {'matched_items':count,'coverage':'Current feed contents only; not a historical archive'}
