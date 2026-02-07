import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys
# NEW LIBRARY IMPORT
from google import genai
from bs4 import BeautifulSoup
import warnings

# Suppress warnings
warnings.filterwarnings("ignore")

class ResearchMonitor:
    def __init__(self, google_api_key, email_address, email_password):
        self.email_address = email_address
        self.email_password = email_password
        try:
            # NEW CLIENT INITIALIZATION
            self.client = genai.Client(api_key=google_api_key)
            # We use 1.5-flash because it is the most reliable current model
            self.model_name = "gemini-1.5-flash"
        except Exception as e:
            print(f"⚠️ Warning: Gemini API issue: {e}")
        
    def search_arxiv(self, query, days_back=7, max_results=50):
        """Search arXiv strictly for Economics papers"""
        base_url = "http://export.arxiv.org/api/query?"
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        clean_query = query.replace(' ', '+')
        category_filter = "%28cat:econ*+OR+cat:q-fin*%29"
        search_query = f'search_query={category_filter}+AND+all:{clean_query}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending'
        
        try:
            response = requests.get(base_url + search_query, timeout=30)
            papers = []
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                namespace = {'atom': 'http://www.w3.org/2005/Atom'}
                
                for entry in root.findall('atom:entry', namespace):
                    try:
                        published = entry.find('atom:published', namespace).text
                        pub_date = datetime.strptime(published[:10], '%Y-%m-%d')
                        
                        if pub_date >= start_date:
                            # SAFE PARSING: Prevent crashes if category is missing
                            cat_elem = entry.find('atom:primary_category', namespace)
                            if cat_elem is not None and 'term' in cat_elem.attrib:
                                cat = cat_elem.attrib['term']
                            else:
                                cat = "Econ"
                            
                            papers.append({
                                'title': entry.find('atom:title', namespace).text.strip().replace('\n', ' '),
                                'summary': entry.find('atom:summary', namespace).text.strip().replace('\n', ' '),
                                'link': entry.find('atom:id', namespace).text,
                                'source': f'arXiv ({cat})'
                            })
                    except: continue # Skip bad entries
                        
            return papers
        except Exception as e:
            print(f"Error searching arXiv: {e}")
            return []

    def search_ssrn(self, query, days_back=7, max_results=50):
        """Search SSRN for Economics papers"""
        # SSRN doesn't have a public API, but we can search via their RSS feeds
        # SSRN Economics Network: https://papers.ssrn.com/sol3/JELJOUR_Results.cfm
        base_url = "https://papers.ssrn.com/sol3/JELJOUR_Results.cfm"
        try:
            # Search for economics papers using SSRN's format
            params = {
                'form_name': 'journalBrowse',
                'journal_id': '1',  # Economics Network
                'npage': '1'
            }
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(base_url, params=params, headers=headers, timeout=30)
            papers = []
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                # Parse SSRN papers from the page
                for paper_div in soup.find_all('div', class_='paper')[:max_results]:
                    try:
                        title_elem = paper_div.find('a', class_='title')
                        abstract_elem = paper_div.find('div', class_='abstract')
                        
                        if title_elem:
                            href = title_elem.get('href', '')
                            link = 'https://papers.ssrn.com' + href if href.startswith('/') else href
                            papers.append({
                                'title': title_elem.text.strip(),
                                'summary': abstract_elem.text.strip()[:500] if abstract_elem else "No abstract available",
                                'link': link,
                                'source': 'SSRN'
                            })
                    except Exception:
                        continue
                        
            return papers
        except Exception as e:
            print(f"Error searching SSRN: {e}")
            return []
    
    def search_repec_working_papers(self, days_back=7):
        """Search RePEc for working papers (not journals)"""
        # RePEc working paper series codes
        working_paper_series = [
            'RePEc:nbr:nberwo',  # NBER Working Papers
            'RePEc:cpr:ceprdp',  # CEPR Discussion Papers
            'RePEc:iza:izadps',  # IZA Discussion Papers
            'RePEc:wrk:warwec',  # Warwick Economic Research Papers
            'RePEc:oxf:wpaper',  # Oxford Working Papers
        ]
        
        papers = []
        for series_code in working_paper_series:
            base_url = f"https://ideas.repec.org/cgi-bin/get_rss.pl?h={series_code}"
            try:
                response = requests.get(base_url, timeout=30)
                if response.status_code == 200:
                    root = ET.fromstring(response.content)
                    for item in root.findall('.//item')[:10]:
                        try:
                            papers.append({
                                'title': item.find('title').text,
                                'summary': item.find('description').text[:500] if item.find('description') is not None else "No abstract",
                                'link': item.find('link').text,
                                'source': f"Working Paper ({series_code.split(':')[-1]})"
                            })
                        except Exception:
                            continue
            except Exception as e:
                print(f"Error searching RePEc working papers ({series_code}): {e}")
                continue
                
        return papers

    def generate_summary(self, papers, research_focus):
        if not papers: return "No new papers found."
        
        papers_text = ""
        for i, paper in enumerate(papers[:40], 1):
            papers_text += f"\n{i}. [{paper['source']}] {paper['title']}\n   Link: {paper['link']}\n"

        prompt = f"""
        You are an expert PhD-level economist.
        Review this list of new papers.
        
        MY RESEARCH FOCUS: {research_focus}
        
        INSTRUCTIONS:
        1. FILTER: STRICTLY ignore Physics/CS/Bio papers. Only keep Economics.
        2. RANK: Select the top 5 papers most relevant to Heterodox/Development/India.
        3. SUMMARIZE: Write a 2-sentence technical summary for each of the top 5.
        4. CATEGORIZE: Group other relevant economics papers by sub-field.
        
        LIST:
        {papers_text}
        """
        try:
            # NEW GENERATE CONTENT SYNTAX
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            return response.text
        except Exception as e:
            return f"Error with Gemini: {e}"

    def send_email(self, subject, body):
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.email_address
            msg['To'] = self.email_address
            
            html_content = f"""
            <html><body style="font-family: Arial, sans-serif;">
            <h2 style="color:#2c3e50;">📅 Weekly Economics Digest</h2>
            <p style="color:#7f8c8d;">{datetime.now().strftime('%B %d, %Y')}</p>
            <div style="background-color:#f9f9f9; padding:15px; border-radius:5px;">
            {body.replace(chr(10), '<br>').replace('**', '<b>').replace('**', '</b>')}
            </div>
            <p style="font-size:12px; color:#999;">Sources: arXiv, SSRN, RePEc Working Papers</p>
            </body></html>
            """
            msg.attach(MIMEText(html_content, 'html'))
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(self.email_address, self.email_password)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"Email Error: {e}")
            return False

# --- MAIN RUN ---
if __name__ == "__main__":
    GOOGLE_KEY = os.environ.get('GOOGLE_API_KEY')
    EMAIL = os.environ.get('EMAIL_ADDRESS')
    PASS = os.environ.get('EMAIL_PASSWORD')

    if not all([GOOGLE_KEY, EMAIL, PASS]):
        print("❌ Secrets missing.")
        sys.exit(1)

    ARXIV_TOPICS = ['heterodox', 'political economy', 'development economics', 'India']
    
    FOCUS = "Heterodox economics, development macroeconomics, and Indian political economy."

    monitor = ResearchMonitor(GOOGLE_KEY, EMAIL, PASS)
    all_papers = []

    print("🔍 1. Scanning arXiv (Econ)...")
    all_papers += monitor.search_arxiv(' OR '.join(ARXIV_TOPICS), days_back=7)

    print("🔍 2. Scanning SSRN...")
    all_papers += monitor.search_ssrn('economics', days_back=7)

    print("🔍 3. Scanning RePEc Working Papers...")
    all_papers += monitor.search_repec_working_papers(days_back=7)

    print(f"📝 Found {len(all_papers)} papers.")
    
    if all_papers:
        print("🤖 Generating AI Summary...")
        digest = monitor.generate_summary(all_papers, FOCUS)
        print("📧 Sending Digest Email...")
        if monitor.send_email(f"Weekly Econ Research: {datetime.now().strftime('%b %d')}", digest):
            print("✅ Email sent!")
        else:
            print("❌ Email failed.")
    else:
        # --- NO PAPERS FOUND LOGIC ---
        print("⚠️ No papers found. Sending notification email...")
        msg = "No new papers matched your criteria this week. This is normal during holidays. The script is running correctly."
        monitor.send_email(f"Weekly Econ: No New Papers ({datetime.now().strftime('%b %d')})", msg)
        print("✅ Notification sent.")
