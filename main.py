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
            self.model = genai.GenerativeModel('gemini-2.5-flash')
        except Exception as e:
            print(f"⚠️ Warning: Gemini API issue: {e}")
        
    def search_arxiv(self, query, days_back=7, max_results=50):
        """Search arXiv for recent papers"""
        base_url = "http://export.arxiv.org/api/query?"
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        query = query.replace(' ', '+')
        search_query = f'search_query=all:{query}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending'
        
        try:
            response = requests.get(base_url + search_query, timeout=30)
            papers = []
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                namespace = {'atom': 'http://www.w3.org/2005/Atom'}
                for entry in root.findall('atom:entry', namespace):
                    published = entry.find('atom:published', namespace).text
                    pub_date = datetime.strptime(published[:10], '%Y-%m-%d')
                    if pub_date >= start_date:
                        papers.append({
                            'title': entry.find('atom:title', namespace).text.strip().replace('\n', ' '),
                            'authors': [a.find('atom:name', namespace).text for a in entry.findall('atom:author', namespace)],
                            'summary': entry.find('atom:summary', namespace).text.strip().replace('\n', ' '),
                            'link': entry.find('atom:id', namespace).text,
                            'source': 'arXiv'
                        })
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
                start_date = datetime.now() - timedelta(days=days_back)
                
                for item in root.findall('.//item')[:10]:
                    try:
                        papers.append({
                            'title': item.find('title').text,
                            'authors': ['Journal Author'], 
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
        """Custom scraper for Ashoka University Research"""
        url = "https://www.ashoka.edu.in/research-listing/"
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = requests.get(url, headers=headers, timeout=30)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            papers = []
            for article in soup.find_all('div', class_='research-listing-item')[:5]:
                try:
                    title_tag = article.find('h3') or article.find('h4')
                    link_tag = article.find('a')
                    if title_tag and link_tag:
                        papers.append({
                            'title': title_tag.text.strip(),
                            'authors': ['Ashoka Faculty'],
                            'summary': "New research listing from Ashoka University website.",
                            'link': link_tag['href'] if 'http' in link_tag['href'] else f"https://www.ashoka.edu.in{link_tag['href']}",
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
        for i, paper in enumerate(papers[:30], 1):
            papers_text += f"\n{i}. [{paper['source']}] {paper['title']}\n   Link: {paper['link']}\n"

        prompt = f"""
        You are an expert research assistant. 
        I have a list of new economics papers from the last week.
        
        My Research Focus: {research_focus}
        
        Task:
        1. Identify the top 5 papers most relevant to my focus.
        2. For these 5, write a ONE-sentence summary of why it's interesting.
        3. Group the rest of the papers by category (e.g., "Macro", "Development", "Other").
        4. Format as a clean, scannable newsletter.
        
        List of Papers:
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
            <h2 style="color:#2c3e50;">📅 Weekly Research Digest</h2>
            <p style="color:#7f8c8d;">{datetime.now().strftime('%B %d, %Y')}</p>
            <div style="background-color:#f9f9f9; padding:15px; border-radius:5px;">
            {body.replace(chr(10), '<br>').replace('**', '<b>').replace('**', '</b>')}
            </div>
            <p style="font-size:12px; color:#999;">Sources: arXiv, RePEc (JPE, RRPE, CJE, JDE, World Dev), Ashoka Univ</p>
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
    # Load secrets from GitHub Environment
    GOOGLE_KEY = os.environ.get('GOOGLE_API_KEY')
    EMAIL = os.environ.get('EMAIL_ADDRESS')
    PASS = os.environ.get('EMAIL_PASSWORD')

    if not all([GOOGLE_KEY, EMAIL, PASS]):
        print("❌ Secrets missing. Make sure they are set in GitHub Settings.")
        sys.exit(1)

    # SEARCH CONFIGURATION
    ARXIV_TOPICS = ['heterodox economics', 'development economics', 'India political economy']
    
    JOURNAL_CODES = [
        'RePEc:ucp:jpolec', 
        'RePEc:sae:reorpe', 
        'RePEc:oup:cambje', 
        'RePEc:eee:deveco', 
        'RePEc:eee:wdevel' 
    ]
    
    FOCUS = "Heterodox economics, development, and Indian political economy."

    monitor = ResearchMonitor(GOOGLE_KEY, EMAIL, PASS)
    all_papers = []

    print("🔍 1. Scanning arXiv (last 7 days)...")
    all_papers += monitor.search_arxiv(' OR '.join(ARXIV_TOPICS), days_back=7)

    print("🔍 2. Scanning Journals...")
    for code in JOURNAL_CODES:
        print(f"   - Checking {code}...")
        all_papers += monitor.search_repec_series(code, days_back=7)

    print("🔍 3. Scraping Ashoka University...")
    all_papers += monitor.scrape_ashoka()

    print(f"📝 Found {len(all_papers)} total papers. Analyzing...")
    
    if all_papers:
        digest = monitor.generate_summary(all_papers, FOCUS)
        print("📧 Sending weekly digest...")
        if monitor.send_email(f"Weekly Research: {datetime.now().strftime('%b %d')}", digest):
            print("✅ Email sent successfully!")
        else:
            print("❌ Email failed.")
    else:
        print("❌ No papers found this week.")
