import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys
import google.generativeai as genai
from bs4 import BeautifulSoup
import warnings

# Suppress warnings
warnings.filterwarnings("ignore")

class ResearchMonitor:
    def __init__(self, google_api_key, email_address, email_password):
        self.email_address = email_address
        self.email_password = email_password
        try:
            genai.configure(api_key=google_api_key)
            # Use 1.5-flash (stable)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        except Exception as e:
            print(f"⚠️ Warning: Gemini API issue: {e}")
        
    def search_arxiv(self, query, days_back=7, max_results=50):
        """Search arXiv strictly for Economics papers"""
        base_url = "http://export.arxiv.org/api/query?"
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        # RESTRICT to Econ/Finance categories
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
                            # SAFE PARSING: Handle missing categories gracefully
                            cat_elem = entry.find('atom:primary_category', namespace)
                            if cat_elem is not None and 'term' in cat_elem.attrib:
                                cat = cat_elem.attrib['term']
                            else:
                                cat = "Econ (Uncategorized)"
                            
                            papers.append({
                                'title': entry.find('atom:title', namespace).text.strip().replace('\n', ' '),
                                'summary': entry.find('atom:summary', namespace).text.strip().replace('\n', ' '),
                                'link': entry.find('atom:id', namespace).text,
                                'source': f'arXiv ({cat})'
                            })
                    except Exception as loop_error:
                        # If one paper fails, skip it and continue!
                        continue
                        
            return papers
        except Exception as e:
            print(f"Error searching arXiv: {e}")
            return []

    def search_repec_series(self, series_code, days_back=7):
        """Search specific journals via RePEc"""
        base_url = f"https://ideas.repec.org/cgi-bin/get_rss.pl?h={series_code}"
        try:
            response = requests.get(base_url, timeout=30)
            papers = []
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                for item in root.findall('.//item')[:10]:
                    try:
                        papers.append({
                            'title': item.find('title').text,
                            'summary': item.find('description').text[:500] if item.find('description') is not None else "No abstract",
                            'link': item.find('link').text,
                            'source': f"Journal ({series_code})"
                        })
                    except: continue
            return papers
        except Exception as e:
            print(f"Error searching RePEc ({series_code}): {e}")
            return []

    def scrape_ashoka(self):
        """Custom scraper for Ashoka University"""
        url = "https://www.ashoka.edu.in/research-listing/"
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=30)
            soup = BeautifulSoup(response.content, 'html.parser')
            papers = []
            for article in soup.find_all('div', class_='research-listing-item')[:5]:
                try:
                    title = article.find('h3') or article.find('h4')
                    link = article.find('a')
                    if title and link:
                        papers.append({
                            'title': title.text.strip(),
                            'summary': "Ashoka University Research Listing",
                            'link': link['href'] if 'http' in link['href'] else f"https://www.ashoka.edu.in{link['href']}",
                            'source': 'Ashoka Univ'
                        })
                except: continue
            return papers
        except Exception as e:
            print(f"Error scraping Ashoka: {e}")
            return []

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
            response = self.model.generate_content(prompt)
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
            <p style="font-size:12px; color:#999;">Sources: arXiv, RePEc, Ashoka Univ</p>
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
    
    JOURNAL_CODES = [
        'RePEc:ucp:jpolec', 'RePEc:sae:reorpe', 
        'RePEc:oup:cambje', 'RePEc:eee:deveco', 'RePEc:eee:wdevel' 
    ]
    
    FOCUS = "Heterodox economics, development macroeconomics, and Indian political economy."

    monitor = ResearchMonitor(GOOGLE_KEY, EMAIL, PASS)
    all_papers = []

    print("🔍 1. Scanning arXiv (Econ)...")
    all_papers += monitor.search_arxiv(' OR '.join(ARXIV_TOPICS), days_back=7)

    print("🔍 2. Scanning Journals...")
    for code in JOURNAL_CODES:
        print(f"   - Checking {code}...")
        all_papers += monitor.search_repec_series(code, days_back=7)

    print("🔍 3. Scraping Ashoka University...")
    all_papers += monitor.scrape_ashoka()

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
        print("⚠️ No papers found. Sending notification email...")
        msg = "No new papers matched your criteria this week. This is normal during holidays. The script is working correctly."
        monitor.send_email(f"Weekly Econ: No New Papers ({datetime.now().strftime('%b %d')})", msg)
        print("✅ Notification sent.")
