from __future__ import print_function
import argparse
from urlparse import urlparse, urlunparse
import re

import requests
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.support.wait import WebDriverWait


EMAIL_RE = re.compile(r"[a-z0-9\.\-+_]+@[a-z0-9\.\-+_]+\.[a-z]+")


class DriverParser:
    """
    This class relies on selenium Firefox driver to download url and parse DOM
    The reason we use driver and not simple requests.get() is because we want to simulate complete browser session
    and wait for page scripts to complete content download.

    DriverParser also uses EMAIL_RE to parse out emails from <body>'s innerHtml
    """

    def __init__(self):
        self.driver = webdriver.Firefox()

    def parse_urls(self):
        """
        generator that iterates over all <a href> elements and yields potential urls
        """
        try:
            for elt in self.driver.find_elements_by_xpath("//a[@href]"):
                try:
                    yield elt.get_attribute("href")
                except WebDriverException:
                    continue
        except WebDriverException:
            pass


    def parse_emails(self):
        """
        Searches <body> part of the html for any string that looks like email

        :return: list of all found email like strings
        """
        try:
            html = self.driver.find_element_by_tag_name("body").get_attribute("innerHTML")
            return list(EMAIL_RE.findall(html, re.I))
        except WebDriverException:
            pass

    def load_and_parse(self, uc, url):
        """
        Uses selenium to download target url.
        If download fail for any reason, ignore the error and skip the parsing
        If page redirects outside domain, skip it.
        Once completely loaded, parse html content for urls and emails.

        :param uc: UrlCollection to add back urls to process
        :param url: to be downloaded and parsed

        :return: list of found emails
        """
        try:
            self.driver.get(url)
            # Looks like the only way to know that page is completely loaded is ask JS engine a question
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete")
        except WebDriverException:
            # TODO: retry ? check error type ?
            return []

        # Drop redirection to outside
        if not uc.should_parse(uc.normalize(self.driver.current_url)):
            return []

        # add to collection all found urls
        map(uc.add_url, self.parse_urls())

        # return all found emails
        return self.parse_emails()


def download_and_parse(uc, url):
    """
    In a world where we do not need browser to download webpage and wait for JS to complete site render
    this function works wonders.

    It uses requests to download url, BeautifulSoup to parse for hrefs and EMAIL_RE to parse out emails.

    :param uc: UrlCollection to add back urls and emails
    :param url: to be downloaded and parsed
    """
    from bs4 import BeautifulSoup

    try:
        response = requests.get(url)
    except:
        # Nothing to do...
        return []

    # setup html parser for url parsing
    soup = BeautifulSoup(response.text, "lxml")

    # add to collection all found urls
    map(uc.add_url, [a.attrs["href"] for a in soup.find_all("a") if "href" in a.attrs])

    return EMAIL_RE.findall(response.text, re.I)


class UrlCollection:
    """
    Used to normalize, validate and keep track of crawled urls.

    Can be used as iterator
    """

    def __init__(self, site):
        # normalize site url
        site = site.strip().lower()
        site = site if site.startswith('http') else "{}://{}".format('http', site)

        # setup

        parsed = urlparse(site)
        # all urls, including from subdomains should have root
        self.root = parsed.netloc
        # fix relative urls with
        self.base_url = "{}://{}".format(parsed.scheme, self.root)
        # normalized urls we have looked at
        self.seen_urls = {site}
        # normalized urls we have plan to work on. This is the collection for iterator interface.
        self.work_urls = {site}
        # resulting set of emails
        self.emails = set()

    def in_root_domain(self, url):
        # is this page from the root domain ?
        return urlparse(url).netloc.endswith(self.root)

    def should_parse(self, url):
        return url and self.in_root_domain(url)

    def should_add(self, url):
        return url \
               and (url not in self.seen_urls) \
               and self.in_root_domain(url)

    def normalize(self, url):
        if not url:
            return None

        # fix relative links
        url = url if not url.startswith('/') else self.base_url + url

        # normalize
        url = url.lower()

        # is it a web page ?
        if not url.startswith('http'):
            return None

        # remove extra bits
        # TODO: could be too harsh of optimization
        parsed = urlparse(url)
        url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, None, None, None))

        return url

    def add_url(self, url):
        """
        Add url to collection. Normalize and filter by domain
        :param url:
        """
        url = self.normalize(url)

        if not self.should_add(url):
            return self

        # mark as seen
        self.seen_urls.add(url)

        # add to work load
        self.work_urls.add(url)

        return self

    def add_email(self, email):
        self.emails.add(str(email))

    def __iter__(self):
        return self

    def next(self):
        """
        Implements iterator interface, removes and returns url from self.work_urls set.

        :return: url to download and parse
        """
        if self.work_urls:
            return self.work_urls.pop()
        else:
            raise StopIteration


def main():
    parser = argparse.ArgumentParser(description='Crawl web site for emails.')
    parser.add_argument('site', type=unicode, help='internet domain name to crawl, like "{}"'.format('jana.com'))

    args = parser.parse_args()

    # Setup
    uc = UrlCollection(args.site)
    dp = DriverParser()

    # Do the crawl
    emails = reduce(lambda x, y: set(x).union(set(y)),
                    map(lambda url: dp.load_and_parse(uc, url), uc))

    # Output results
    if emails:
        print('Found these email addresses:')
        map(print, emails)
    else:
        print('Could not find emails')


if __name__ == '__main__':
    main()

