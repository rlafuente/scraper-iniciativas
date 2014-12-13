#!/usr/bin/env python
# -*- coding: utf-8 -*-

from hashlib import sha1
import os
import urllib
import shutil
from bs4 import BeautifulSoup
import re
from itertools import chain
from datetime import datetime as dt
import json
import codecs
import click
from zenlog import log
import multiprocessing


DEFAULT_MAX = 5000

ROMAN_NUMERALS = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5,
                  'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10,
                  'XI': 11, 'XII': 12, 'XIII': 13, 'XIV': 14, 'XV': 15,
                  'XVI': 16, 'XVII': 17, 'XVIII': 18, 'XIX': 19, 'XX': 20,
                  'XXI': 21, 'XXII': 22, 'XXIII': 23, 'XXIV': 24, 'XXV': 25}

FORMATTER_URL_IL = 'http://www.parlamento.pt/ActividadeParlamentar/Paginas/DetalheIniciativa.aspx?BID=%d'

RE_NORESULTS = re.compile('NoResults')
RE_TITLE = re.compile('lblTitulo')
RE_SUMMARY = re.compile('lblDocumentoTitulo')
RE_DOCLINK = re.compile('hplDocumentoDOC')
RE_PDFLINK = re.compile('hplDocumentoPDF')
RE_AUTHOR = re.compile('hplAutor')
RE_PARLGROUP = re.compile('lblDeputadosGP')
RE_DISTDATE = re.compile('lblDataDistribuicao')

RE_EVENTDATE = re.compile('lblData$')
RE_EVENTTYPE = re.compile('lblEvento')
RE_EVENTINFO = re.compile('pnlDiscussao')


def hash(str):
    hash = sha1()
    hash.update(str)
    return hash.hexdigest()


def file_get_contents(file):
    return open(file).read()


def fix_encoding(contents):
    return contents.decode('cp1252')


def file_put_contents(file, contents, utf8=True):
    f = codecs.open(file, 'w+', 'utf-8')
    c = contents.decode('utf-8').replace('\r', '')
    f.write(c)
    f.close()


def getpage(url):
    if not os.path.exists('cache'):
        log.info('Creating new cache/ folder.')
        os.mkdir('cache')
    url_hash = hash(url)
    cache_file = 'cache/' + url_hash

    if os.path.exists(cache_file):
        log.debug("Cache hit for %s" % url)
        page = file_get_contents(cache_file)
    else:
        log.debug("Cache miss for %s" % url)
        page = urllib.urlopen(url).read()
        file_put_contents(cache_file, page, utf8=True)
    return page


def extract_details(block):
    return [item.text.strip() for item in block.find_all('tr')[1:]]


def extract_multiline_details(block):
    return [item.strip(" ;,") for item in chain.from_iterable(tr.text.split('\n') for tr in block.find_all('tr')[1:]) if item]


def process_dep(i):
    log.debug("Trying ID %d..." % i)

    url = FORMATTER_URL_IL % i
    soup = BeautifulSoup(getpage(url), "lxml")
    title = soup.find('span', id=RE_TITLE)
    if title:
        summary = soup.find('span', id=RE_SUMMARY)
        doc_url = soup.find('a', id=RE_DOCLINK)
        pdf_url = soup.find('a', id=RE_PDFLINK)
        eventdates = soup.findAll('span', id=RE_EVENTDATE)
        eventtypes = soup.findAll('span', id=RE_EVENTTYPE)
        eventinfos = soup.findAll('div', id=RE_EVENTINFO)
        dist_date = soup.find('span', id=RE_DISTDATE)
        authors = soup.findAll('a', id=RE_AUTHOR)
        parlgroup = soup.find('span', id=RE_PARLGROUP)

        deprow = {'title': title.text,
                  'summary': summary.text,
                  'id': i,
                  'url': url,
                  'authors': [a.text for a in authors],
                  'scrape_date': dt.utcnow().isoformat(), }

        if doc_url:
            deprow['doc_url'] = doc_url['href']
        if pdf_url:
            deprow['pdf_url'] = pdf_url['href']
        if dist_date:
            deprow['dist_date'] = dist_date.text
        if parlgroup:
            deprow['parlgroup'] = parlgroup.text

        for index, eventdate in enumerate(eventdates):
            event = {'date': eventdate.text}
            event['type'] = eventtypes[index].text.strip()
            info = eventinfos[index].text.strip()
            if info:
                # TODO: Processar esta informação
                event['info'] = info
            if not deprow.get('events'):
                deprow['events'] = []
            deprow['events'].append(event)

        log.info("Scraped initiative: %s" % title.text)

        return deprow
    else:
        return None


def scrape(format, start=1, end=None, verbose=False, outfile='', indent=1, processes=2):
    deprows = {}
    if processes > 1:
        pool = multiprocessing.Pool(processes=processes)
        max = end

        try:
            # processed_deps = (proced_dep for proced_dep in pool.map(process_dep, range(start, max), chunksize=4) if proced_dep)
            processed_deps = (proced_dep for proced_dep in pool.map(process_dep, range(start, max), chunksize=4) if proced_dep)
        except KeyboardInterrupt:
            pool.terminate()
    else:
        processed_deps = []
        for x in range(start, end):
            processed_deps.append(process_dep(x))

    for processed_dep in processed_deps:
        if not processed_dep:
            continue
        deprows[processed_dep['title']] = processed_dep

    log.info("Saving to file %s..." % outfile)
    depsfp = codecs.open(outfile, 'w+', 'utf-8')
    depsfp.write(json.dumps(deprows, encoding='utf-8', ensure_ascii=False, indent=indent, sort_keys=True))
    depsfp.close()
    log.info("Done.")


@click.command()
@click.option("-f", "--format", help="Output file format, can be json (default) or csv", default="json")
@click.option("-s", "--start", type=int, help="Begin scrape from this ID (int required, default 0)", default=0)
@click.option("-e", "--end", type=int, help="End scrape at this ID (int required, default 5000)", default=5000)
@click.option("-v", "--verbose", is_flag=True, help="Print some helpful information when running")
@click.option("-o", "--outfile", type=click.Path(), help="Output file (default is deputados.json)")
@click.option("-i", "--indent", type=int, help="Spaces for JSON indentation (default is 2)", default=2)
@click.option("-p", "--processes", type=int, help="Simultaneous processes to run (default is 2)", default=2)
@click.option("-c", "--clear-cache", help="Clean the local webpage cache", is_flag=True)
def main(format, start, end, verbose, outfile, indent, clear_cache, processes):
    if not outfile and format == "csv":
        outfile = "iniciativas.csv"
    elif not outfile and format == "json":
        outfile = "iniciativas.json"
    if clear_cache:
        log.info("Clearing old cache...")
        shutil.rmtree("cache/")

    scrape(format, start, end, verbose, outfile, indent, processes)

if __name__ == "__main__":
    main()
