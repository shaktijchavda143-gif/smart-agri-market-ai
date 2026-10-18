import sys
from email.utils import format_datetime
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, '/mnt/data/newswork/ai_backend')
import main

now = datetime.now(timezone.utc)
rows = [
 ('TV9 Gujarati','https://tv9gujarati.com/a','TV9 ખેડૂત માટે MSP પર મહત્વના સમાચાર'),
 ('ABP Asmita','https://gujarati.abplive.com/a','ABP ખેડૂતો માટે નવી કૃષિ સહાય યોજના'),
 ('Sandesh','https://sandesh.com/a','Sandesh ખેતી પાક માટે વરસાદની માહિતી'),
 ('Gujarat Samachar','https://www.gujaratsamachar.com/a','Gujarat Samachar ખેડૂતો માટે પાક વીમો'),
 ('Mumbai Samachar','https://bombaysamachar.com/a','Mumbai Samachar કૃષિ બજાર ભાવ ખેડૂતો માટે'),
 ('Gujarat First','https://www.gujaratfirst.com/a','Gujarat First ખેડૂતને સિંચાઈ સહાય'),
 ('VTV Gujarati','https://www.vtvgujarati.com/a','VTV ખેડૂતો માટે ખાતર અને બિયારણ'),
 ('GSTV','https://www.gstv.in/a','GSTV પાક નુકસાન અને ખેડૂતોને વળતર'),
 ('News18 Gujarati','https://gujarati.news18.com/a','News18 Gujarati કૃષિ યોજનાનો લાભ ખેડૂતોને'),
 ('Zee 24 Kalak','https://www.zee24kalak.in/a','Zee 24 Kalak ખેડૂતો માટે ખેતી સમાચાર'),
 ('Jamavat','https://www.jamawat.com/a','Jamavat ખેડૂત અને કૃષિ બજાર સમાચાર'),
 ('Facebook','https://facebook.com/somepost','Facebook ખેડૂત ખેતી સમાચાર'),
]
items=[]
for src,url,title in rows:
    items.append(f'''<item><title>{title}</title><link>{url}</link><pubDate>{format_datetime(now - timedelta(hours=3))}</pubDate><source url="{urlparse(url).scheme}://{urlparse(url).netloc}">{src}</source><description>{title}</description></item>''')
rss=('<?xml version="1.0"?><rss><channel>'+''.join(items)+'</channel></rss>').encode()

class Resp:
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def read(self,n=-1): return rss
class Req:
    def __init__(self,url,headers=None): self.url=url

def fake(req, timeout=8):
    return Resp()

main.urllib.request.urlopen = fake
result = main._fetch_news_items('Gujarat agriculture farmer news', limit=12, category='all', max_age_hours=48)
print('RESULT_COUNT', len(result))
print('SOURCES', sorted({x['source'] for x in result}))
print('SCORES', [(x['source'], x.get('farmer_relevance')) for x in result])
print('DIAG', main._LAST_NEWS_FETCH_DIAGNOSTICS)
assert len(result) >= 8
assert 'Facebook' not in {x['source'] for x in result}
assert len({x['source'] for x in result}) >= 8
assert all(x.get('farmer_relevance',0) >= 0.22 for x in result)
assert main._approved_news_source('Facebook', 'https://facebook.com/x') is None
assert main._approved_news_source('Sandesh', 'https://sandesh.com/x') == 'Sandesh'
assert main._approved_news_source('VTV', 'https://vtvgujarati.com/x') == 'VTV Gujarati'
print('FORENSIC_NEWS_TEST=PASS')
assert main._farmer_relevance_score('ગુજરાતમાં ફિલ્મ સ્ટારનું આગમન') == 0.0
assert main._farmer_relevance_score('ખેડૂતો માટે MSP અને પાક વીમાની નવી જાહેરાત') >= 0.44
assert main._approved_news_source('TV9 Gujarati', 'https://facebook.com/tv9gujarati') is None
print('GENERAL_NEWS_REJECTION=PASS')
print('FACEBOOK_SPOOF_REJECTION=PASS')
