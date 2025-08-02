from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import time
import requests
import json
from datetime import datetime
import logging

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.serve_dashboard()
        elif self.path == '/api/status':
            self.serve_status_api()
        elif self.path == '/api/stats':
            self.serve_stats_api()
        else:
            self.send_error(404)
    
    def serve_dashboard(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Keep Alive Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .header p {
            font-size: 1.2em;
            opacity: 0.9;
        }
        
        .dashboard {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.15);
        }
        
        .card h3 {
            color: #4a5568;
            margin-bottom: 15px;
            font-size: 1.3em;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background-color: #48bb78;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }
        
        .metric {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #e2e8f0;
        }
        
        .metric:last-child {
            border-bottom: none;
        }
        
        .metric-label {
            color: #718096;
            font-weight: 500;
        }
        
        .metric-value {
            color: #2d3748;
            font-weight: 600;
            font-size: 1.1em;
        }
        
        .logs {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        }
        
        .logs h3 {
            color: #4a5568;
            margin-bottom: 15px;
            font-size: 1.3em;
        }
        
        .log-container {
            background: #1a202c;
            border-radius: 8px;
            padding: 15px;
            max-height: 300px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }
        
        .log-entry {
            color: #a0aec0;
            margin-bottom: 5px;
            line-height: 1.4;
        }
        
        .log-entry.success {
            color: #68d391;
        }
        
        .log-entry.error {
            color: #fc8181;
        }
        
        .log-entry.info {
            color: #63b3ed;
        }
        
        .refresh-btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 1em;
            font-weight: 600;
            transition: transform 0.2s ease;
            margin-top: 15px;
        }
        
        .refresh-btn:hover {
            transform: scale(1.05);
        }
        
        .auto-refresh {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-top: 15px;
            color: #718096;
        }
        
        .switch {
            position: relative;
            width: 50px;
            height: 24px;
        }
        
        .switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        
        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: .4s;
            border-radius: 24px;
        }
        
        .slider:before {
            position: absolute;
            content: "";
            height: 18px;
            width: 18px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }
        
        input:checked + .slider {
            background-color: #667eea;
        }
        
        input:checked + .slider:before {
            transform: translateX(26px);
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Keep Alive Dashboard</h1>
            <p>Monitoring your bot's heartbeat and performance</p>
        </div>
        
        <div class="dashboard">
            <div class="card">
                <h3>
                    <span class="status-indicator"></span>
                    System Status
                </h3>
                <div class="metric">
                    <span class="metric-label">Server Status</span>
                    <span class="metric-value" id="server-status">Online</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Uptime</span>
                    <span class="metric-value" id="uptime">Loading...</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Last Ping</span>
                    <span class="metric-value" id="last-ping">Loading...</span>
                </div>
            </div>
            
            <div class="card">
                <h3>📊 Performance Stats</h3>
                <div class="metric">
                    <span class="metric-label">Total Requests</span>
                    <span class="metric-value" id="total-requests">Loading...</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Successful Pings</span>
                    <span class="metric-value" id="successful-pings">Loading...</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Failed Pings</span>
                    <span class="metric-value" id="failed-pings">Loading...</span>
                </div>
            </div>
            
            <div class="card">
                <h3>⚙️ Configuration</h3>
                <div class="metric">
                    <span class="metric-label">Ping Interval</span>
                    <span class="metric-value" id="ping-interval">5 minutes</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Server Port</span>
                    <span class="metric-value">8080</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Auto Ping</span>
                    <span class="metric-value">Enabled</span>
                </div>
            </div>
        </div>
        
        <div class="logs">
            <h3>📝 Activity Logs</h3>
            <div class="log-container" id="logs">
                <div class="log-entry info">[INFO] Keep alive server started successfully</div>
                <div class="log-entry success">[SUCCESS] Auto-ping system initialized</div>
                <div class="log-entry info">[INFO] Dashboard ready and monitoring...</div>
            </div>
            <button class="refresh-btn" onclick="refreshData()">Refresh Data</button>
            <div class="auto-refresh">
                <label class="switch">
                    <input type="checkbox" id="auto-refresh-toggle" checked onchange="toggleAutoRefresh()">
                    <span class="slider"></span>
                </label>
                <span>Auto-refresh every 30 seconds</span>
            </div>
        </div>
    </div>
    
    <script>
        let autoRefreshInterval;
        let startTime = Date.now();
        
        function formatUptime(ms) {
            const seconds = Math.floor(ms / 1000);
            const minutes = Math.floor(seconds / 60);
            const hours = Math.floor(minutes / 60);
            const days = Math.floor(hours / 24);
            
            if (days > 0) return `${days}d ${hours % 24}h ${minutes % 60}m`;
            if (hours > 0) return `${hours}h ${minutes % 60}m ${seconds % 60}s`;
            if (minutes > 0) return `${minutes}m ${seconds % 60}s`;
            return `${seconds}s`;
        }
        
        function updateUptime() {
            const uptime = Date.now() - startTime;
            document.getElementById('uptime').textContent = formatUptime(uptime);
        }
        
        function addLog(message, type = 'info') {
            const logsContainer = document.getElementById('logs');
            const timestamp = new Date().toLocaleTimeString();
            const logEntry = document.createElement('div');
            logEntry.className = `log-entry ${type}`;
            logEntry.textContent = `[${timestamp}] ${message}`;
            logsContainer.appendChild(logEntry);
            logsContainer.scrollTop = logsContainer.scrollHeight;
            
            // Keep only last 50 log entries
            while (logsContainer.children.length > 50) {
                logsContainer.removeChild(logsContainer.firstChild);
            }
        }
        
        async function refreshData() {
            try {
                const response = await fetch('/api/stats');
                const stats = await response.json();
                
                document.getElementById('total-requests').textContent = stats.total_requests || '0';
                document.getElementById('successful-pings').textContent = stats.successful_pings || '0';
                document.getElementById('failed-pings').textContent = stats.failed_pings || '0';
                document.getElementById('last-ping').textContent = stats.last_ping || 'Never';
                
                addLog('Dashboard data refreshed', 'success');
            } catch (error) {
                addLog('Failed to refresh data: ' + error.message, 'error');
            }
        }
        
        function toggleAutoRefresh() {
            const toggle = document.getElementById('auto-refresh-toggle');
            if (toggle.checked) {
                autoRefreshInterval = setInterval(refreshData, 30000);
                addLog('Auto-refresh enabled', 'info');
            } else {
                clearInterval(autoRefreshInterval);
                addLog('Auto-refresh disabled', 'info');
            }
        }
        
        // Initialize
        document.addEventListener('DOMContentLoaded', function() {
            updateUptime();
            setInterval(updateUptime, 1000);
            refreshData();
            toggleAutoRefresh();
            
            // Simulate some activity
            setTimeout(() => addLog('Ping successful - Bot is alive!', 'success'), 2000);
            setTimeout(() => addLog('System health check completed', 'info'), 5000);
        });
    </script>
</body>
</html>
        """
        
        self.wfile.write(html_content.encode())
    
    def serve_status_api(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
        status = {
            'status': 'online',
            'timestamp': datetime.now().isoformat(),
            'uptime': time.time() - KeepAliveServer.start_time if hasattr(KeepAliveServer, 'start_time') else 0
        }
        
        self.wfile.write(json.dumps(status).encode())
    
    def serve_stats_api(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
        stats = getattr(KeepAliveServer, 'stats', {
            'total_requests': 0,
            'successful_pings': 0,
            'failed_pings': 0,
            'last_ping': 'Never'
        })
        
        self.wfile.write(json.dumps(stats).encode())
    
    def log_message(self, format, *args):
        # Suppress HTTP server logs
        pass

class KeepAliveServer:
    def __init__(self, port=8080, ping_url=None, ping_interval=300):
        self.port = port
        self.ping_url = ping_url
        self.ping_interval = ping_interval  # Default 5 minutes
        self.server = None
        self.ping_thread = None
        self.running = False
        
        # Initialize stats
        KeepAliveServer.start_time = time.time()
        KeepAliveServer.stats = {
            'total_requests': 0,
            'successful_pings': 0,
            'failed_pings': 0,
            'last_ping': 'Never'
        }
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('keepalive.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def run_server(self):
        """Run the HTTP server"""
        try:
            self.server = HTTPServer(('0.0.0.0', self.port), KeepAliveHandler)
            self.logger.info(f"Keep alive server started on port {self.port}")
            self.server.serve_forever()
        except Exception as e:
            self.logger.error(f"Server error: {e}")
    
    def ping_self(self):
        """Ping the server itself or external URL to keep it alive"""
        while self.running:
            try:
                # Ping self by default, or external URL if provided
                url = self.ping_url or f"http://localhost:{self.port}"
                
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    KeepAliveServer.stats['successful_pings'] += 1
                    KeepAliveServer.stats['last_ping'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self.logger.info(f"✓ Ping successful: {url}")
                else:
                    KeepAliveServer.stats['failed_pings'] += 1
                    self.logger.warning(f"✗ Ping failed with status {response.status_code}: {url}")
                    
                KeepAliveServer.stats['total_requests'] += 1
                
            except requests.exceptions.RequestException as e:
                KeepAliveServer.stats['failed_pings'] += 1
                KeepAliveServer.stats['total_requests'] += 1
                self.logger.error(f"✗ Ping error: {e}")
            
            # Wait for next ping
            time.sleep(self.ping_interval)
    
    def start(self):
        """Start the keep alive server and auto-ping"""
        self.running = True
        
        # Start HTTP server in a separate thread
        server_thread = Thread(target=self.run_server)
        server_thread.daemon = True
        server_thread.start()
        
        # Start auto-ping in a separate thread if enabled
        if self.ping_interval > 0:
            self.ping_thread = Thread(target=self.ping_self)
            self.ping_thread.daemon = True
            self.ping_thread.start()
            self.logger.info(f"Auto-ping started with {self.ping_interval}s interval")
        
        return self
    
    def stop(self):
        """Stop the keep alive server"""
        self.running = False
        if self.server:
            self.server.shutdown()
        self.logger.info("Keep alive server stopped")

# Convenience function for backward compatibility
def keep_alive(port=8080, ping_url=None, ping_interval=300):
    """
    Start the enhanced keep alive server with auto-ping
    
    Args:
        port (int): Port to run the server on (default: 8080)
        ping_url (str): URL to ping (default: self-ping)
        ping_interval (int): Seconds between pings (default: 300 = 5 minutes)
    """
    server = KeepAliveServer(port=port, ping_url=ping_url, ping_interval=ping_interval)
    return server.start()

# Example usage
if __name__ == "__main__":
    # Start with default settings
    keep_alive()
    
    # Or customize settings
    # keep_alive(port=8080, ping_url="https://your-bot-url.com", ping_interval=300)
    
    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
