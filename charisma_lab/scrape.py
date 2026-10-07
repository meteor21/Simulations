"""Optional allowlisted article extraction. No login, paywall, CAPTCHA or robots bypass."""
from __future__ import annotations
from urllib.parse import urljoin,urlsplit
from urllib.robotparser import RobotFileParser
from .network import AccessBlocked,BudgetExceeded,require_public_url
from .store import unpack_body
from .util import allowed_host,host,now

class Scraper:
    def __init__(self,client,allowed_domains):
        self.client=client; self.allowed_domains=tuple(allowed_domains); self.robots={}
        if not self.allowed_domains: raise ValueError('Enable permitted_fetch for appropriate outlets before scraping.')

    def allowed(self,url):
        if not allowed_host(url,self.allowed_domains): raise AccessBlocked('Domain is not opted in for full-text fetching.')
        require_public_url(url)
        root=f'{urlsplit(url).scheme}://{urlsplit(url).netloc}'
        if root not in self.robots:
            r=self.client.get(root+'/robots.txt',max_bytes=500_000,min_interval=2)
            if r.status_code==404: self.robots[root]=True
            elif r.status_code==200:
                parser=RobotFileParser(); parser.parse(r.text.splitlines()); self.robots[root]=parser
            else: raise AccessBlocked('Robots policy could not be verified.')
        rule=self.robots[root]
        if rule is not True and not rule.can_fetch('CandidateStandingResearch',url):
            raise AccessBlocked('robots.txt disallows fetching this path.')
        crawl_delay=None if rule is True else rule.crawl_delay('CandidateStandingResearch')
        request_rate=None if rule is True else rule.request_rate('CandidateStandingResearch')
        rate_interval=(request_rate.seconds/request_rate.requests) if request_rate and request_rate.requests else 0
        return max(2.0,float(crawl_delay or 0),rate_interval)

    def fetch(self,url):
        import trafilatura
        for _ in range(5):
            interval=self.allowed(url)
            r=self.client.get(url,min_interval=interval,max_bytes=2_000_000)
            if 300<=r.status_code<400:
                url=urljoin(url,r.headers.get('Location','')); continue
            if r.status_code!=200: raise AccessBlocked(f'Article HTTP status {r.status_code}')
            if 'html' not in r.headers.get('Content-Type','').lower(): raise AccessBlocked('Not an HTML article.')
            text=trafilatura.extract(r.text,include_comments=False,include_tables=False,favor_precision=True)
            if not text or len(text)<200: raise AccessBlocked('No substantial accessible article body; not circumventing access restrictions.')
            meta=trafilatura.extract_metadata(r.text,default_url=url)
            return {'body':text,'title':getattr(meta,'title',None),'date':getattr(meta,'date',None),'fetched_url':url}
        raise AccessBlocked('Too many redirects.')


def run_fetch(store,scraper,*,max_articles=100,checkpoint_path=None,retry_failed=False):
    # One URL fetch is reused for all candidates; stored text is compressed in SQLite.
    where='' if retry_failed else ' AND NOT EXISTS (SELECT 1 FROM cs_fetch_log f WHERE f.article_id=a.article_id)'
    rows=store.rows("""SELECT a.* FROM cs_articles a WHERE NOT EXISTS
      (SELECT 1 FROM cs_versions v WHERE v.article_id=a.article_id AND v.body_z IS NOT NULL)"""+where+' LIMIT ?', (max_articles,))
    out={'fetched':0,'blocked':0}
    try:
        for a in rows:
            if not allowed_host(a['url'],scraper.allowed_domains): continue
            try:
                data=scraper.fetch(a['url']); t=now()
                candidates=[r['candidate_id'] for r in store.rows('SELECT candidate_id FROM cs_article_candidates WHERE article_id=?',(a['article_id'],))]
                prior=store.rows('SELECT * FROM cs_versions WHERE article_id=? ORDER BY retrieved_at DESC LIMIT 1',(a['article_id'],))[0]
                store.article(url=a['url'],title=data['title'] or prior['title'],candidate_ids=candidates,body=data['body'],
                    published_at=data['date'] or prior['published_at'],indexed_at=prior['indexed_at'],retrieved_at=t,
                    rights_note='User-opted-in public-page extraction; comply with publisher terms; do not redistribute text.',
                    metadata={'fetched_url':data['fetched_url'],'extractor':'trafilatura','date_is_publisher_estimate':True})
                store.con.execute('INSERT INTO cs_fetch_log(article_id,attempted_at,status,message) VALUES(?,?,?,?)',(a['article_id'],t,'ok',''))
                store.con.commit(); out['fetched']+=1
            except BudgetExceeded: break
            except Exception as e:
                store.con.rollback()
                store.con.execute('INSERT INTO cs_fetch_log(article_id,attempted_at,status,message) VALUES(?,?,?,?)',
                                  (a['article_id'],now(),'blocked',type(e).__name__))
                store.con.commit(); out['blocked']+=1
            if checkpoint_path and sum(out.values())%10==0: store.backup(checkpoint_path)
    finally:
        if checkpoint_path: store.backup(checkpoint_path)
    return out
