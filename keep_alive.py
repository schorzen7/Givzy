import os
import time
import requests
import logging
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Bot Keep Alive</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; 
                       background: linear-gradient(135deg, #667eea, #764ba2); color: white; }}
                .container {{ background: rgba(255,255,255,0.1); padding: 30px; border-radius: 15px; 
                            backdrop-filter: blur(10px); display: inline-block; }}
                .status {{ color: #4ade80; font-size: 24px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🤖 Bot Keep Alive Server</h1>
                <div class="status">✅ Status: Online</div>
                <p>Server is running on port {os.environ.get('PORT', 8080)}</p>
                <p>Last ping: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode())
    
    def log_message(self, format, *args):
        # Suppress HTTP server logs to reduce spam
        pass

class KeepAlive:
    def __init__(self):
        self.port = int(os.environ.get('PORT', 8080))
        self.ping_interval = 300  # 5 minutes
        self.running = False
    
    def start_server(self):
        """Start the HTTP server"""
        try:
            server = HTTPServer(('0.0.0.0', self.port), SimpleHandler)
            logger.info(f"Keep alive server started on port {self.port}")
            server.serve_forever()
        except Exception as e:
            logger.error(f"Server error: {e}")
    
    def auto_ping(self):
        """Auto ping to keep the server alive"""
        while self.running:
            try:
                # Ping self
                url = f"http://localhost:{self.port}"
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    logger.info("✅ Auto-ping successful")
                else:
                    logger.warning(f"⚠️ Auto-ping returned status {response.status_code}")
            except Exception as e:
                logger.error(f"❌ Auto-ping failed: {e}")
            
            # Wait before next ping
            time.sleep(self.ping_interval)
    
    def start(self):
        """Start the keep alive system"""
        self.running = True
        
        # Start server in background thread
        server_thread = Thread(target=self.start_server)
        server_thread.daemon = True
        server_thread.start()
        
        # Start auto-ping in background thread
        ping_thread = Thread(target=self.auto_ping)
        ping_thread.daemon = True
        ping_thread.start()
        
        logger.info("🚀 Keep alive system started with auto-ping every 5 minutes")

def keep_alive():
    """Simple function to start keep alive server"""
    server = KeepAlive()
    server.start()

if __name__ == "__main__":
    keep_alive()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
