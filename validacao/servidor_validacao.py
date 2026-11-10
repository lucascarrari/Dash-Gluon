import sys, runpy
from pathlib import Path
p=Path(__file__).resolve().parent
sys.path[:0]=[str(p/'deps'),str(p.parent/'soilframe-dashboard'),str(p.parent/'soilframe-voronoi-master'/'soilframe')]
sys.argv=['streamlit','run',str(p.parent/'soilframe-dashboard'/'app.py'),'--server.headless=true','--server.address=127.0.0.1','--server.port=8517','--browser.gatherUsageStats=false']
runpy.run_module('streamlit',run_name='__main__')
