"""Build a self-contained public visual report from a saved, analyzed checkpoint."""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import re
from pathlib import Path

from .dashboard_data import SCOPES, build_dashboard_data

COLORS = {'national': '#187e75', 'state': '#619de3', 'metro': '#9775ca',
          'local': '#d08d38', 'unknown': '#8c959e'}

PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Explore the evidence, coverage gaps and review status of the Midterm Sentiment Agents pilot.">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>Midterm / Media Observatory</title>
<style>
:root{--ink:#152b32;--muted:#587077;--line:#dce5e4;--paper:#f5f7f6;--teal:#187e75;--mint:#dcefe9;--amber:#8c5b1d;--amber-bg:#fff3dc;--white:#fff;--shadow:0 8px 32px #203d3a06}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:var(--teal);text-underline-offset:3px}button,input,select{font:inherit}button,a,input,select{outline-offset:4px}button{cursor:pointer}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #72b8ae}button:disabled{cursor:default}svg{display:block}h1,h2,h3,p{margin:0}h1{font-size:clamp(32px,4vw,50px);line-height:1.12;letter-spacing:-1.8px;font-weight:640}h2{font-size:21px;line-height:1.3;letter-spacing:-.45px}h3{font-size:16px;font-weight:650}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-variant-numeric:tabular-nums}.muted{color:var(--muted)}.small{font-size:12px}.eyebrow{text-transform:uppercase;letter-spacing:1.6px;font-size:10px;font-weight:750}.wrap{max-width:1280px;margin:auto;padding:0 40px}.topbar{background:#132e35;color:#fff}.topline{min-height:76px;display:flex;align-items:center;justify-content:space-between;gap:24px}.brand{display:flex;align-items:center;gap:12px;font-size:15px;letter-spacing:.5px;font-weight:650;color:white;text-decoration:none}.brandmark{width:31px;height:31px;border:1px solid #62918e;border-radius:8px;display:grid;place-items:center}.brandmark span{width:13px;height:13px;border:2px solid #a8ddcd;transform:rotate(45deg)}.brand small{display:block;font-size:10px;letter-spacing:2.2px;color:#99b9ba;font-weight:500}.topnav{display:flex;gap:27px;align-items:center}.topnav a{font-size:12px;color:#c5d7d7;text-decoration:none}.topnav a:hover{color:#fff}.cycle{border:1px solid #547473;border-radius:20px;padding:4px 12px;color:#c4e0d8;font-size:11px}.hero{padding:43px 0 29px;display:grid;grid-template-columns:1fr auto;gap:30px;align-items:center}.hero .eyebrow{color:var(--teal);margin-bottom:11px}.hero p{max-width:680px;margin-top:14px;color:var(--muted);font-size:14px}.hero-actions{display:flex;gap:9px;flex-wrap:wrap;justify-content:flex-end}.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:1px solid var(--line);border-radius:7px;padding:9px 14px;background:#fff;color:var(--ink);text-decoration:none;font-size:12px;font-weight:650;white-space:nowrap}.btn.primary{background:var(--teal);color:white;border-color:var(--teal)}.btn:hover{filter:brightness(.97)}.status-strip{display:flex;justify-content:space-between;align-items:center;gap:20px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:13px 0;margin-bottom:24px;font-size:12px}.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 9px;border-radius:5px;background:#edf2f1;color:#526970;font-size:11px;font-weight:600}.pill.amber{background:var(--amber-bg);color:var(--amber)}.pill.green{background:var(--mint);color:#166a5d}.dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:currentColor}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin-bottom:20px}.stat{border:1px solid var(--line);border-radius:10px;background:white;padding:20px 23px;box-shadow:var(--shadow)}.stat-top{display:flex;justify-content:space-between;align-items:center;font-size:11px;font-weight:650;color:var(--muted)}.stat-value{font-size:39px;font-weight:650;line-height:1.3;letter-spacing:-1.3px;margin:8px 0 3px}.stat-note{font-size:11px;color:var(--muted)}.stat .status-icon{width:23px;height:23px;border-radius:6px;background:var(--paper);display:grid;place-items:center;font-size:12px}.stat .missing{color:var(--amber)}.panel{background:#fff;border:1px solid var(--line);border-radius:11px;box-shadow:var(--shadow);padding:25px;margin-bottom:20px}.panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;margin-bottom:23px}.panel-head p{font-size:12px;color:var(--muted);margin-top:5px}.grid-main{display:grid;grid-template-columns:1.75fr 1fr;gap:20px}.scope-tabs{display:inline-flex;border:1px solid var(--line);border-radius:6px;padding:3px;background:#f7f9f8;gap:2px}.scope-tabs button{border:0;background:transparent;padding:5px 10px;border-radius:4px;font-size:11px;color:var(--muted)}.scope-tabs button[aria-pressed=true]{background:white;box-shadow:0 1px 4px #102b3014;color:var(--ink);font-weight:650}.bars{display:flex;flex-direction:column;gap:20px;padding:3px 0 13px}.bar-row{display:grid;grid-template-columns:71px minmax(20px,1fr) 25px;gap:13px;align-items:center;font-size:12px}.bar-track{height:22px;border-radius:4px;background:#f0f4f3;position:relative}.bar-fill{height:100%;min-width:0;border-radius:4px;background:var(--teal);transition:width .22s ease}.bar-empty{position:absolute;top:1px;left:10px;color:#7a8c90;font-size:10px;line-height:20px}.chart-note{font-size:11px;color:var(--muted);border-top:1px solid #edf1f0;padding-top:13px;line-height:1.65}.budget-layout{display:flex;gap:22px;align-items:center;margin:4px 0 19px}.ring{width:132px;flex:0 0 132px;position:relative}.ring svg{width:132px;height:132px;transform:rotate(-90deg)}.ring-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}.ring-center strong{font-size:30px;line-height:1.15;letter-spacing:-1px}.ring-center span{font-size:11px;color:var(--muted)}.budget-detail .line{display:flex;align-items:center;gap:7px;font-size:12px;margin:7px 0}.swatch{width:8px;height:8px;background:var(--teal);border-radius:2px}.swatch.gray{background:#e8efed}.quiet-note{padding:11px 12px;border-radius:6px;background:#f3f8f6;font-size:11px;color:#426b61}.pipeline{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.stage{padding:16px;border:1px solid #e4eae8;background:#f9fbfa;border-radius:7px;position:relative}.stage:after{content:'›';position:absolute;right:-11px;top:28px;color:#96a9a8;font-size:20px;z-index:1}.stage:last-child:after{content:none}.stage .step{color:#758b8e;font-size:9px;letter-spacing:1.1px;text-transform:uppercase}.stage strong{display:block;font-size:26px;font-weight:650;line-height:1.6}.stage p{font-size:11px;color:var(--muted)}.stage.pending{background:#fffaf0;border-color:#f1e5cd}.stage.pending strong{color:var(--amber)}.filters{display:flex;gap:10px;align-items:center;margin-bottom:15px;flex-wrap:wrap}.search{position:relative;flex:1;min-width:180px}.search input{width:100%;border:1px solid var(--line);border-radius:6px;background:#fafcfb;padding:9px 12px;font-size:12px;color:var(--ink)}select{border:1px solid var(--line);border-radius:6px;background:#fff;padding:9px 28px 9px 11px;font-size:12px;color:var(--ink);max-width:100%}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;text-align:left;font-size:12px}th{font-size:9px;color:#6c8287;letter-spacing:.8px;text-transform:uppercase;padding:11px 12px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);background:#f9fbfa;white-space:nowrap}td{padding:12px;border-bottom:1px solid #edf1f0;vertical-align:middle}.candidate-name{font-weight:650;max-width:250px;display:block;line-height:1.35}.candidate-id{display:block;font-size:10px;color:#74888b;margin-top:3px}.candidate-open{border:0;background:none;text-align:left;padding:0;color:var(--ink)}.candidate-open:hover .candidate-name{text-decoration:underline;text-underline-offset:3px}.scope-cells{display:flex;gap:4px}.scope-count{width:25px;padding:3px 0;display:inline-block;text-align:center;background:#eff3f2;color:#8a9b9d;border-radius:3px;font-size:10px}.scope-count.observed{background:#e3f1eb;color:#1c776c;font-weight:700}.score-missing{font-size:11px;color:#7a6749;white-space:nowrap}.legend{display:flex;gap:14px;align-items:center;flex-wrap:wrap;font-size:10px;color:var(--muted)}.table-footer{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-top:15px;font-size:11px;color:var(--muted)}.candidate-detail{margin-top:15px;border:1px solid #cfdfda;border-radius:8px;padding:18px;background:#f5faf7}.detail-top{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.close{background:none;border:0;font-size:19px;color:var(--muted);line-height:1}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:13px;font-size:12px}.detail-grid ul{padding-left:17px;margin:4px 0}.detail-grid li{margin:4px 0}.detail-grid a{overflow-wrap:anywhere}.details-meta{font-size:11px;color:var(--muted);margin-top:4px}.source-list{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.source-card{border:1px solid #e2e9e6;border-radius:7px;padding:15px}.source-card .domain{font-weight:650;font-size:12px;overflow-wrap:anywhere}.source-card .source-meta{font-size:10px;color:var(--muted);margin:7px 0}.source-card .pill{font-size:10px}.source-card details{font-size:10px;color:var(--muted);margin-top:10px}.source-card summary{cursor:pointer;color:#587877}.source-card details p{margin-top:5px;overflow-wrap:anywhere}.source-card .source-evidence{display:block;margin-top:5px}.sources-foot{margin-top:15px;font-size:11px;color:var(--muted)}.methods{display:grid;grid-template-columns:repeat(3,1fr);gap:25px}.method-index{font-size:10px;color:var(--teal);font-weight:700;margin-bottom:8px;letter-spacing:1px}.methods h3{font-size:14px;margin-bottom:6px}.methods p{font-size:12px;color:var(--muted)}.evidence-links{display:flex;gap:18px;flex-wrap:wrap;margin-top:22px;padding-top:17px;border-top:1px solid var(--line);font-size:11px}.footer{display:flex;justify-content:space-between;gap:20px;padding:9px 0 32px;color:#6e8387;font-size:10px}.empty-state{text-align:center;padding:30px;color:var(--muted)}.noscript{padding:20px;background:var(--amber-bg)}[hidden]{display:none!important}.skip-link{position:absolute;left:-9999px;top:10px}.skip-link:focus{left:20px;z-index:10;background:white;padding:10px}
@media(max-width:1050px){.hero{grid-template-columns:1fr}.hero-actions{justify-content:flex-start}.grid-main{grid-template-columns:1.45fr 1fr}.budget-layout{gap:10px}.ring{flex-basis:110px;width:110px}.ring svg{width:110px;height:110px}.source-list{grid-template-columns:repeat(2,1fr)}}
@media(max-width:720px){.wrap{padding:0 18px}.topline{min-height:67px}.topnav{gap:13px}.topnav a{font-size:11px}.topnav a:nth-child(3),.cycle{display:none}.brand{font-size:12px}.brand small{font-size:8px}.hero{padding:29px 0 22px;gap:18px}.hero p{font-size:12px}.status-strip{align-items:flex-start;flex-direction:column;gap:7px;font-size:11px}.stats{grid-template-columns:repeat(2,1fr);gap:10px}.stat{padding:15px}.stat-value{font-size:33px}.stat-top{font-size:10px}.stat-note{font-size:10px}.grid-main{grid-template-columns:1fr;gap:0}.panel{padding:18px}.panel-head{gap:12px;flex-wrap:wrap;margin-bottom:18px}h2{font-size:19px}.pipeline{grid-template-columns:repeat(2,1fr);gap:8px}.stage{padding:12px}.stage:last-child{grid-column:1/-1}.stage:after{content:none}.source-list{grid-template-columns:1fr}.methods{grid-template-columns:1fr;gap:18px}.footer,.table-footer{flex-direction:column;align-items:flex-start;gap:7px}.detail-grid{grid-template-columns:1fr;gap:13px}.budget-layout{gap:25px}.ring{flex-basis:132px;width:132px}.ring svg{width:132px;height:132px}.filters select{flex:1}.filters .search{flex-basis:100%}.scope-tabs button{font-size:10px;padding:5px 8px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}.bar-fill{transition:none}}
</style>
</head>
<body>
<a href="#overview" class="skip-link">Skip to analysis</a>
<header class="topbar"><div class="wrap topline"><a class="brand" href="#overview"><span class="brandmark" aria-hidden="true"><span></span></span><span>MIDTERM<small>MEDIA OBSERVATORY</small></span></a><nav class="topnav" aria-label="Main"><a href="#overview">Overview</a><a href="#candidates">Candidates</a><a href="#sources">Sources</a><span class="cycle" id="cycle-label"></span></nav></div></header>
<noscript><div class="wrap noscript">This interactive view needs JavaScript. Open the <a href="README.md">visual report</a> or download <a href="candidate_coverage.csv">candidate data</a>.</div></noscript>
<main class="wrap" id="overview">
<section class="hero"><div><div class="eyebrow">Evidence before interpretation</div><h1>A clear view of the<br>media pilot.</h1><p id="hero-caption">Explore candidate coverage, source availability, and the evidence needed for sentiment analysis.</p></div><div class="hero-actions"><a class="btn" href="candidate_coverage.csv" download>↓ Candidate data</a><a class="btn primary" id="analysis-link" href="#method">View analysis run ↗</a></div></section>
<div class="status-strip"><div><span class="pill amber"><span class="dot"></span><span id="coverage-status">Partial coverage</span></span> <span class="muted">&nbsp;Saved data · retrospective research</span></div><div id="date-window" class="mono"></div></div>
<section class="stats" aria-label="Pilot summary">
<div class="stat"><div class="stat-top">CONGRESSIONAL REGISTRATIONS<span class="status-icon" aria-hidden="true">◎</span></div><div class="stat-value mono" id="stat-candidates">—</div><div class="stat-note">Selected FEC identities · not a certified ballot</div></div>
<div class="stat"><div class="stat-top">SAVED NEWS URLS<span class="status-icon" aria-hidden="true">↗</span></div><div class="stat-value mono" id="stat-articles">—</div><div class="stat-note">Within the original collection window</div></div>
<div class="stat"><div class="stat-top">REVIEWED LABELS<span class="status-icon" aria-hidden="true">✓</span></div><div class="stat-value mono" id="stat-reviews">—</div><div class="stat-note">Candidate-specific annotations</div></div>
<div class="stat"><div class="stat-top">AVAILABLE SENTIMENT SCORES<span class="status-icon" aria-hidden="true">◷</span></div><div class="stat-value mono missing" id="stat-scores">—</div><div class="stat-note" id="scores-note">Missing values remain unavailable</div></div>
</section>
<div class="grid-main"><section class="panel" aria-labelledby="coverage-title"><div class="panel-head"><div><h2 id="coverage-title">Where coverage comes from</h2><p>Saved URL counts by source geography</p></div><div class="scope-tabs" role="group" aria-label="Coverage unit"><button type="button" data-unit="urls" aria-pressed="true">URLs</button><button type="button" data-unit="candidates" aria-pressed="false">Candidates</button></div></div><div class="bars" id="coverage-bars" role="img" aria-label="Coverage by source scope"></div><p class="chart-note" id="coverage-note"></p></section>
<section class="panel" aria-labelledby="budget-title"><div class="panel-head"><div><h2 id="budget-title">A bounded collection</h2><p>One allowance across collection and retries</p></div><span class="pill green">No new requests</span></div><div class="budget-layout"><div class="ring"><svg viewBox="0 0 132 132" role="img" aria-label="Provider request budget"><circle cx="66" cy="66" r="55" fill="none" stroke="#e8efed" stroke-width="12"/><circle id="budget-arc" cx="66" cy="66" r="55" fill="none" stroke="#187e75" stroke-width="12" stroke-linecap="round"/></svg><div class="ring-center"><strong class="mono" id="budget-used">—</strong><span id="budget-limit"></span></div></div><div class="budget-detail"><div class="line"><span class="swatch"></span><span id="requests-used"></span></div><div class="line"><span class="swatch gray"></span><span id="requests-left"></span></div><div class="muted small" id="requests-analysis"></div></div></div><div class="quiet-note">Analysis reuses the saved checkpoint. This dashboard does not collect new articles.</div></section></div>
<section class="panel" aria-labelledby="pipeline-title"><div class="panel-head"><div><h2 id="pipeline-title">From collection to usable evidence</h2><p>Each step has its own unit. Search results still need candidate verification and review.</p></div><span class="pill amber" id="pipeline-status">Awaiting sentiment review</span></div><div class="pipeline" id="pipeline"></div></section>
<section class="panel" id="candidates" aria-labelledby="candidates-title"><div class="panel-head"><div><h2 id="candidates-title">Explore the candidates</h2><p>Select a name to inspect its evidence and missingness.</p></div><span class="pill">Registration discovery</span></div><div class="filters"><label class="search"><span class="eyebrow" hidden>Search candidates</span><input id="candidate-search" type="search" aria-label="Search candidates" placeholder="Search a name or FEC ID…"></label><select id="chamber-filter" aria-label="Filter by chamber"><option value="">All chambers</option><option value="H">House</option><option value="S">Senate</option></select><select id="state-filter" aria-label="Filter by state"><option value="">All states</option></select><select id="coverage-filter" aria-label="Filter by coverage"><option value="">All coverage</option><option value="observed">Has search-linked URLs</option><option value="missing">No saved URLs</option></select></div><div class="table-wrap"><table><thead><tr><th>Candidate / FEC identity</th><th>Race</th><th>Party</th><th>Search-linked URLs</th><th>Scope · N / S / M / L / ?</th><th>Sentiment score</th></tr></thead><tbody id="candidate-rows"></tbody></table></div><div id="candidate-empty" class="empty-state" hidden>No candidates match these filters. Clear a filter to see the roster.</div><div class="table-footer"><span id="candidate-count" aria-live="polite"></span><span>URL associations are unreviewed search matches, not verified mentions.</span></div><section class="candidate-detail" id="candidate-detail" hidden aria-label="Selected candidate evidence"></section></section>
<section class="panel" id="sources" aria-labelledby="sources-title"><div class="panel-head"><div><h2 id="sources-title">Which sources were available?</h2><p>A source-directory match enables a search. It does not establish complete archive coverage.</p></div><div class="scope-tabs" role="group" aria-label="Source list"><button type="button" data-source-mode="attempted" aria-pressed="true">Looked up</button><button type="button" data-source-mode="all" aria-pressed="false">Relevant catalog</button></div></div><div class="source-list" id="source-list"></div><p class="sources-foot" id="source-note"></p></section>
<section class="panel" id="method" aria-labelledby="method-title"><div class="panel-head"><div><h2 id="method-title">How to read this pilot</h2><p>Three distinctions keep the results interpretable.</p></div></div><div class="methods"><div><div class="method-index">01 / CANDIDATES</div><h3>Registrations need confirmation</h3><p>The roster contains sourced FEC registration identities. Ballot status, race membership and documented periods in office are separate research facts.</p></div><div><div class="method-index">02 / SENTIMENT</div><h3>Missing is not neutral</h3><p>Sentiment needs reviewed, candidate-specific evidence and sufficient coverage. A search match alone produces no sentiment score. News portrayal is separate from survey favorability.</p></div><div><div class="method-index">03 / TIME & SOURCES</div><h3>A fixed window, partial coverage</h3><p>This is a retrospective view of the original collection window. It is not a point-in-time forecast. Source partisanship carries no automatic penalty; no source rating is inferred here.</p></div></div><div class="evidence-links"><a id="collection-link" href="#">Original collection ↗</a><a href="data.json" download>Public metadata JSON ↓</a><a id="notebook-link" href="#">Open Colab ↗</a><a id="code-link" href="#">Source and audit ↗</a></div></section>
<footer class="footer"><span>Midterm Sentiment Agents · Public metadata only · No article text or private reviews</span><span class="mono" id="revision"></span></footer>
</main>
<script id="dashboard-data" type="application/json">__DASHBOARD_JSON__</script>
<script>
'use strict';
const D=JSON.parse(document.getElementById('dashboard-data').textContent);
const scopes=['national','state','metro','local','unknown'];
const colors={national:'#187e75',state:'#619de3',metro:'#9775ca',local:'#d08d38',unknown:'#8c959e'};
const $=id=>document.getElementById(id);
const text=(id,value)=>{$(id).textContent=String(value)};
const el=(tag,cls,value)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(value!==undefined)node.textContent=String(value);return node};
const pretty=value=>value ? value[0].toUpperCase()+value.slice(1) : 'Unknown';
const date=value=>value ? new Date(value.slice(0,10)+'T12:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}) : 'Not documented';
const link=(label,url,cls)=>{const a=el('a',cls,label);if(url&&/^https?:\/\//.test(url)){a.href=url;a.target='_blank';a.rel='noopener noreferrer'}return a};
const repo='https://github.com/'+D.provenance.source_repository;
text('cycle-label',D.window.cycle+' RESEARCH PILOT');
text('hero-caption',D.summary.selected_candidates+' congressional registrations. One bounded collection window. Explore what was collected, what is missing, and what still needs review.');
text('date-window',date(D.window.start)+' — '+date(D.window.as_of));
text('stat-candidates',D.summary.selected_candidates);text('stat-articles',D.summary.article_urls);text('stat-reviews',D.summary.reviewed_annotations);text('stat-scores',D.summary.candidates_with_scores+' / '+D.summary.selected_candidates);
text('scores-note',D.summary.reviewed_annotations===0?'No reviewed labels · scores remain missing':'Reviewed features where coverage is sufficient');
if(D.summary.reviewed_annotations>0)text('pipeline-status','Coverage and review status');
text('budget-used',D.budget.used);text('budget-limit','of '+D.budget.limit+' requests');
text('requests-used',D.budget.used+' requests used');text('requests-left',D.budget.remaining+' remaining');text('requests-analysis',D.budget.provider_requests_this_analysis+' used by this analysis');
const circumference=2*Math.PI*55;$('budget-arc').setAttribute('stroke-dasharray',circumference);$('budget-arc').setAttribute('stroke-dashoffset',circumference*(1-D.budget.used/D.budget.limit));
$('analysis-link').href=repo+'/actions/runs/'+D.provenance.analysis_run_id;$('collection-link').href=repo+'/actions/runs/'+D.provenance.source_run_id;$('code-link').href=repo+'/tree/'+D.provenance.code_revision;
$('notebook-link').href='https://colab.research.google.com/github/'+D.provenance.source_repository+'/blob/main/notebooks/Midterm_Sentiment_Agents_Colab.ipynb';text('revision','Analysis '+D.provenance.analysis_run_id+' · '+D.provenance.code_revision.slice(0,7));
function renderCoverage(unit='urls'){
 const values=unit==='urls'?D.coverage:Object.fromEntries(scopes.map(s=>[s,D.candidates.filter(c=>c.coverage[s]>0).length]));
 const max=Math.max(1,...Object.values(values));$('coverage-bars').replaceChildren();
 scopes.forEach(scope=>{const row=el('div','bar-row');row.append(el('span','',pretty(scope)));const track=el('div','bar-track');const fill=el('div','bar-fill');fill.style.width=(100*values[scope]/max)+'%';fill.style.background=colors[scope];track.append(fill);if(!values[scope])track.append(el('span','bar-empty','No observed '+(unit==='urls'?'URLs':'candidates')));row.append(track,el('strong','mono',values[scope]));$('coverage-bars').append(row)});
 $('coverage-bars').setAttribute('aria-label',scopes.map(s=>s+': '+values[s]).join('; '));
 text('coverage-note',(unit==='urls'?'Unique saved URLs in the selected cohort and original window. Zero URLs is a coverage gap; source geography does not establish candidate-state or district relevance.':'Candidates with at least one search-linked URL in each source scope. One candidate can appear in multiple scopes; these are unreviewed associations.')+(D.summary.retrospective_scope_urls?' Geography for '+D.summary.retrospective_scope_urls+' URL(s) uses profiles whose historical applicability is unverified.':''));
}
document.querySelectorAll('[data-unit]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-unit]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));renderCoverage(button.dataset.unit)}));renderCoverage();
const attempted=D.sources.filter(s=>s.resolution_status!=='not_requested');const resolved=new Set(attempted.filter(s=>s.resolution_status==='exact_root_homepage_match').map(s=>s.domain)).size;
[['01 · Directory',resolved,'sources resolved',false],['02 · Search',D.collection.processed_jobs??'—','completed jobs',false],['03 · Collection',D.summary.article_urls,'saved news URLs',false],['04 · Review',D.summary.reviewed_annotations,'reviewed annotations',D.summary.reviewed_annotations===0],['05 · Features',D.summary.candidates_with_scores,'candidates with a score',D.summary.candidates_with_scores<D.summary.selected_candidates]].forEach(([label,n,caption,pending])=>{const stage=el('div','stage'+(pending?' pending':''));stage.append(el('div','step',label),el('strong','mono',n),el('p','',caption));$('pipeline').append(stage)});
const states=[...new Set(D.candidates.map(c=>c.state))].sort();states.forEach(state=>{const option=el('option','',state);option.value=state;$('state-filter').append(option)});
function scoreLabel(candidate){const score=candidate.features.media_recency_score;return score!==null&&score!==undefined?Number(score).toFixed(1):candidate.reviewed_annotations===0?'Awaiting review':'Insufficient coverage'}
function renderCandidates(){
 const query=$('candidate-search').value.trim().toLowerCase(),chamber=$('chamber-filter').value,state=$('state-filter').value,coverage=$('coverage-filter').value;
 const selected=D.candidates.filter(c=>(!query||(c.name+' '+c.candidate_id).toLowerCase().includes(query))&&(!chamber||c.office===chamber)&&(!state||c.state===state)&&(!coverage||(coverage==='observed'?c.article_count>0:c.article_count===0)));
 $('candidate-rows').replaceChildren();
 selected.forEach(c=>{const row=el('tr');row.dataset.candidateRow=c.candidate_id;const nameCell=el('td');const button=el('button','candidate-open');button.type='button';button.setAttribute('aria-label','Inspect '+c.name);button.append(el('span','candidate-name',c.name),el('span','candidate-id mono',c.candidate_id));button.addEventListener('click',()=>showCandidate(c));nameCell.append(button);row.append(nameCell,el('td','',c.state+' · '+(c.office==='H'?'House '+(c.district||'at-large'):'Senate')),el('td','',c.party||'Unknown'),el('td','mono',c.article_count));const scopeCell=el('td');const cells=el('div','scope-cells');scopes.forEach(s=>{const count=el('span','scope-count'+(c.coverage[s]?' observed':''),c.coverage[s]);count.title=pretty(s)+': '+c.coverage[s]+' search-linked URLs';cells.append(count)});scopeCell.append(cells);row.append(scopeCell,el('td',c.features.media_recency_score===null?'score-missing':'mono',scoreLabel(c)));$('candidate-rows').append(row)});
 text('candidate-count','Showing '+selected.length+' of '+D.candidates.length+' registrations');$('candidate-empty').hidden=selected.length>0;$('candidate-detail').hidden=true;
}
['candidate-search','chamber-filter','state-filter','coverage-filter'].forEach(id=>$(id).addEventListener(id==='candidate-search'?'input':'change',renderCandidates));renderCandidates();
const missingLabels={no_article_metadata_in_original_window:'No saved article metadata in this collection window.',no_reviewed_candidate_sentiment:'No reviewed candidate-specific sentiment labels.',no_matching_reviewed_snapshot:'No matching reviewed feature snapshot at the cutoff.',feature_lookback_provenance_unavailable:'The feature lookback window is not documented.',sentiment_unavailable:'A usable sentiment score is unavailable.'};
function showCandidate(c){
 const box=$('candidate-detail');box.replaceChildren();box.hidden=false;const top=el('div','detail-top');const title=el('div');title.append(el('h3','',c.name),el('p','details-meta',c.candidate_id+' · '+c.roster_status+' · known '+date(c.known_at)));const close=el('button','close','×');close.type='button';close.setAttribute('aria-label','Close candidate evidence');close.addEventListener('click',()=>{box.hidden=true;document.querySelector('[data-candidate-row="'+CSS.escape(c.candidate_id)+'"] button')?.focus()});top.append(title,close);box.append(top);const grid=el('div','detail-grid');const left=el('div');left.append(el('strong','',scoreLabel(c)));const list=el('ul');c.missingness.forEach(reason=>list.append(el('li','',missingLabels[reason]||'Additional coverage limitation')));if(!c.missingness.length)list.append(el('li','','Scores use available reviewed evidence; coverage limits still apply.'));left.append(list);if(c.source_url)left.append(link('Registration provenance ↗',c.source_url));const right=el('div');right.append(el('strong','','Search-linked publisher URLs'));const articles=D.articles.filter(a=>a.candidate_ids.includes(c.candidate_id));if(!articles.length)right.append(el('p','muted','No saved URLs for this identity in the original window.'));articles.forEach(a=>{const p=el('p');p.append(link(a.domain+' · '+date(a.published_at)+' ↗',a.url));right.append(p)});right.append(el('p','details-meta','Links reflect search associations. Candidate mentions still require verification.'));grid.append(left,right);box.append(grid);
 const provenance=c.feature_provenance;
 if(provenance)box.append(el('p','details-meta','Feature lookback: '+provenance.lookback_days+' days ('+date(provenance.lookback_start)+' to '+date(provenance.as_of)+'). Metadata counts above use only the original collection window.'));
 if(articles.some(a=>!a.historical_scope_verified))box.append(el('p','details-meta','Some article geography uses source profiles whose historical applicability is unverified.'));
 box.tabIndex=-1;box.focus({preventScroll:true});box.scrollIntoView({block:'nearest',behavior:'instant'});
}
const resolutionLabels={exact_root_homepage_match:'Source matched',not_found:'No directory match',not_requested:'Not looked up',directory_incomplete:'Directory incomplete',ambiguous:'Ambiguous match',budget_stop:'Budget stopped lookup',error:'Lookup error',access_blocked:'Access blocked'};
function renderSources(mode='attempted'){
 const sources=D.sources.filter(s=>mode==='all'||s.resolution_status!=='not_requested');$('source-list').replaceChildren();
 sources.forEach(s=>{const card=el('article','source-card');card.append(el('div','domain',s.domain),el('div','source-meta',pretty(s.scope)+(s.states.length?' · '+s.states.join(', '):'')));card.append(el('span','pill '+(s.resolution_status==='exact_root_homepage_match'?'green':s.resolution_status==='not_requested'?'':'amber'),resolutionLabels[s.resolution_status]||'Unknown'));const detail=el('details');detail.append(el('summary','','Geography provenance'));detail.append(el('p','','Observed '+date(s.observed_at)),el('p','','Applicable from '+date(s.valid_from)+(s.valid_to?' through '+date(s.valid_to):'; no end date recorded')));if(s.evidence_url)detail.append(link('Source evidence ↗',s.evidence_url,'source-evidence'));if(s.source_id!==null)detail.append(el('p','mono','Media Cloud ID '+s.source_id));card.append(detail);$('source-list').append(card)});
 text('source-note',mode==='attempted'?resolved+' matched domains from '+new Set(attempted.map(s=>s.domain)).size+' attempted lookups. An unmatched source remains unknown coverage; it may still publish campaign news.':sources.length+' relevant profile records, including sources outside this bounded lookup. Catalog inclusion does not mean an outlet was searched.');
}
document.querySelectorAll('[data-source-mode]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-source-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));renderSources(button.dataset.sourceMode)}));renderSources();
window.__dashboardReady=true;
</script>
</body></html>
'''


def _svg_frame(title, inner, *, width=1000, height=300):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title, quote=True)}">'
            f'<title>{html.escape(title)}</title><rect width="100%" height="100%" rx="12" fill="#f7faf8"/>'
            '<g font-family="system-ui,sans-serif" fill="#152b32">' + inner + '</g></svg>\n')


def _text(x, y, value, *, size=14, color='#152b32', weight=400):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
            f'font-weight="{weight}">{html.escape(str(value))}</text>')


def coverage_svg(data):
    maximum = max(1, *data['coverage'].values())
    parts = [_text(28, 38, 'Saved news URLs by source geography', size=22, weight=650),
             _text(28, 61, 'Selected cohort · original collection window · unreviewed search associations', size=12, color='#587077')]
    for i, scope in enumerate(SCOPES):
        y = 92 + i * 36
        count = data['coverage'][scope]
        parts += [_text(28, y + 15, scope.title()),
                  f'<rect x="133" y="{y}" width="755" height="22" rx="4" fill="#e8efed"/>',
                  f'<rect x="133" y="{y}" width="{755*count/maximum:.2f}" height="22" rx="4" fill="{COLORS[scope]}"/>',
                  _text(916, y + 16, count, size=15, weight=650)]
        if not count:
            parts.append(_text(145, y + 15, 'No observed URLs', size=11, color='#6c8387'))
    parts.append(_text(28, 299, 'Zero saved URLs is a coverage gap. It is not a neutral sentiment score.', size=12, color='#587077'))
    return _svg_frame('Coverage by source geography', ''.join(parts), height=322)


def pipeline_svg(data):
    resolved = len({s['domain'] for s in data['sources'] if s['resolution_status'] == 'exact_root_homepage_match'})
    stages = [('Sources matched', resolved), ('Search jobs done', data['collection'].get('processed_jobs')),
              ('News URLs saved', data['summary']['article_urls']), ('Reviewed labels', data['summary']['reviewed_annotations']),
              ('Candidate scores', data['summary']['candidates_with_scores'])]
    parts = [_text(28, 37, 'From collection to usable evidence', size=22, weight=650)]
    for i, (label, value) in enumerate(stages):
        x = 28 + i*192
        parts.append(f'<rect x="{x}" y="61" width="176" height="99" rx="7" fill="{"#fff1d9" if i>2 and not value else "#e7f1ec"}"/>')
        parts += [_text(x+15, 87, label, size=12, color='#587077'), _text(x+15, 136, value if value is not None else '—', size=35, weight=650)]
    parts.append(_text(28, 193, 'Each step has a different unit. Search results need candidate verification and sentiment review.', size=12, color='#587077'))
    return _svg_frame('Collection and review pipeline', ''.join(parts), height=218)


def budget_svg(data):
    budget = data['budget']
    parts = [_text(28, 36, f"Provider request allowance: {budget['used']} / {budget['limit']}", size=22, weight=650),
             '<rect x="28" y="61" width="940" height="28" rx="5" fill="#e4ece8"/>',
             f'<rect x="28" y="61" width="{940*budget["used"]/budget["limit"]:.2f}" height="28" rx="5" fill="#187e75"/>',
             _text(28, 120, f"{budget['remaining']} requests remain. This analysis used {budget['provider_requests_this_analysis']} new provider requests.", size=13, color='#587077')]
    return _svg_frame('Provider request allowance', ''.join(parts), height=148)


def _csv_cell(value):
    # Exported names/party fields can be opened in spreadsheet applications.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
        return "'" + value
    return '' if value is None else value


def candidate_csv(data):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['candidate_id', 'name', 'office', 'state', 'district', 'party', 'roster_status',
                     'search_linked_urls', *[s+'_urls' for s in SCOPES], 'reviewed_annotations',
                     'media_recency_score', 'national_score', 'subnational_score', 'as_of', 'mode'])
    for c in data['candidates']:
        writer.writerow([_csv_cell(v) for v in [c['candidate_id'], c['name'], c['office'], c['state'],
            c['district'], c['party'], c['roster_status'], c['article_count'],
            *[c['coverage'][s] for s in SCOPES], c['reviewed_annotations'],
            c['features']['media_recency_score'], c['features']['national_score'], c['features']['subnational_score'],
            data['window']['as_of'], data['window']['mode']]])
    return output.getvalue()


def _md(value):
    escaped = html.escape(str(value)).replace('|', '&#124;').replace('\n', ' ').replace('\r', ' ')
    return re.sub(r'([\\`*{}\[\]()#+!_])', r'\\\1', escaped)


def visual_report(data):
    p, s, w, b = data['provenance'], data['summary'], data['window'], data['budget']
    repo = 'https://github.com/' + p['source_repository']
    lines = ['# Midterm / Media Observatory', '',
        f"**{s['selected_candidates']} congressional registrations · {s['article_urls']} saved news URLs · {s['reviewed_annotations']} reviewed labels**", '',
        f"Original window: **{w['start']} through {w['as_of']}**. Retrospective research; coverage is partial.", '',
        f"[Open analysis run]({repo}/actions/runs/{p['analysis_run_id']}) · [Download interactive dashboard](https://raw.githubusercontent.com/{p['source_repository']}/analysis-dashboard/index.html) · [Candidate CSV](candidate_coverage.csv) · [Public metadata](data.json)", '',
        'The HTML dashboard is self-contained: save `index.html` and open it in a browser to search candidates, filter coverage and inspect sources.', '',
        '## Coverage and review', '', '![Saved URLs by source geography](coverage.svg)', '',
        '![Collection and review pipeline](pipeline.svg)', '',
        f"Source geography for **{s.get('retrospective_scope_urls', 0)} saved URLs** uses profiles whose historical applicability is unverified. Geographic scope describes the outlet; it does not establish candidate-state relevance or district readership.", '',
        f"**{s['candidates_with_scores']} of {s['selected_candidates']} candidates have usable reviewed sentiment scores.** Missing values remain unavailable; they are never filled with neutral values.", '',
        '## Collection allowance', '', '![Provider request allowance](budget.svg)', '',
        f"**{b['used']}/{b['limit']} requests used; {b['remaining']} remaining.** This analysis made zero provider requests. Earlier attempts remain charged.", '',
        '## Candidate evidence', '', 'URL counts below are **unreviewed search associations**, not verified candidate mentions. FEC registrations are not certified ballot contestants.', '',
        '| Candidate | Race | Party | Search-linked URLs | Reviewed labels | Sentiment |',
        '|---|---|---|---:|---:|---|']
    for c in data['candidates']:
        score = c['features']['media_recency_score']
        label = f'{score:.1f}' if score is not None else ('Awaiting review' if not c['reviewed_annotations'] else 'Insufficient coverage')
        lines.append('| ' + ' | '.join(_md(v) for v in [c['name']+' ('+c['candidate_id']+')',
            c['state']+' '+('House '+c['district'] if c['office']=='H' else 'Senate'), c['party'],
            c['article_count'], c['reviewed_annotations'], label]) + ' |')
    lines += ['', '## Source lookups', '', '| Source | Geography | Result |', '|---|---|---|']
    for source in data['sources']:
        if source['resolution_status'] != 'not_requested':
            lines.append('| ' + ' | '.join(_md(v) for v in [source['domain'],
                source['scope']+(' / '+', '.join(source['states']) if source['states'] else ''), source['resolution_status']]) + ' |')
    lines += ['', 'Directory absence does not establish that an outlet published no campaign news. Dated source geography provenance is retained in the interactive dashboard and public JSON.', '',
        '## Interpretation', '', 'Media portrayal is not representative public opinion. Survey favorability remains separate. Source partisanship has no automatic weight penalty. This small retrospective pilot does not establish sentiment accuracy or forecasting value.', '',
        'Only selected-cohort public metadata is published here. Article bodies, titles, private review evidence, credentials and the database are excluded. Any available sentiment feature has its own documented lookback window in the public JSON; this is separate from the collection-window metadata counts.', '',
        f"[Original collection]({repo}/actions/runs/{p['source_run_id']}) · [Analysis source]({repo}/tree/{p['code_revision']}) · [Colab notebook](https://colab.research.google.com/github/{p['source_repository']}/blob/main/notebooks/Midterm_Sentiment_Agents_Colab.ipynb)", '']
    return '\n'.join(lines)


def write_dashboard(data, output):
    """Write only public dashboard files to an empty, dedicated output folder."""
    output = Path(output).absolute()
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError('Dashboard output must not use symlinks')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Dashboard output must be a new or empty dedicated folder')
    payload = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
    # JSON script elements still obey HTML's </script> terminator rules.
    inline = payload.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    output.mkdir(parents=True, exist_ok=True)
    files = {'index.html': PAGE.replace('__DASHBOARD_JSON__', inline), 'data.json': payload+'\n',
             'candidate_coverage.csv': candidate_csv(data), 'README.md': visual_report(data),
             'coverage.svg': coverage_svg(data), 'pipeline.svg': pipeline_svg(data),
             'budget.svg': budget_svg(data), '.nojekyll': '',
             '.midterm-dashboard.json': json.dumps({'format': 'midterm-public-dashboard-v1',
                 'source_repository': data['provenance']['source_repository'],
                 'source_run_id': data['provenance']['source_run_id'],
                 'analysis_run_id': data['provenance']['analysis_run_id'],
                 'code_revision': data['provenance']['code_revision']}, indent=2)+'\n'}
    for name, content in files.items():
        (output/name).write_text(content, encoding='utf-8')
    return {'output_files': sorted(files), 'summary': data['summary'], 'budget': data['budget']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--analysis-run-id', default=os.environ.get('GITHUB_RUN_ID'))
    parser.add_argument('--code-revision', default=os.environ.get('GITHUB_SHA'))
    args = parser.parse_args(argv)
    data = build_dashboard_data(args.pilot, source_repository=args.repository,
                               analysis_run_id=args.analysis_run_id, code_revision=args.code_revision)
    result = write_dashboard(data, args.output)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
