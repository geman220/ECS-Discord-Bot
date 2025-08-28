#!/usr/bin/env python3
"""
Security monitoring script for ECS Discord Bot Portal.
Monitors logs for suspicious activity and generates alerts.
"""
import re
import sys
import json
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from pathlib import Path

class SecurityMonitor:
    """Monitor security events and generate alerts."""
    
    def __init__(self):
        self.attack_patterns = {
            'php_exploit': re.compile(r'\.php[^a-zA-Z0-9]', re.IGNORECASE),
            'cms_exploit': re.compile(r'/(wp-|plus/|utility/|vendor/phpunit)', re.IGNORECASE),
            'sql_injection': re.compile(r'\b(union\s+select|drop\s+table|information_schema)\b', re.IGNORECASE),
            'shell_upload': re.compile(r'(file_put_contents|eval|base64_decode)', re.IGNORECASE),
            'path_traversal': re.compile(r'\.\.\/|\.\.\\'),
        }
        
        self.suspicious_ips = defaultdict(int)
        self.attack_types = defaultdict(int)
        self.alerts = []
    
    def analyze_log_line(self, line):
        """Analyze a single log line for security violations."""
        try:
            # Look for IP address (common log format)
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
            if not ip_match:
                return
            
            ip = ip_match.group(1)
            
            # Check for attack patterns
            for attack_name, pattern in self.attack_patterns.items():
                if pattern.search(line):
                    self.suspicious_ips[ip] += 1
                    self.attack_types[attack_name] += 1
                    
                    # Generate alert for high-frequency attacks
                    if self.suspicious_ips[ip] > 10:
                        self.alerts.append({
                            'timestamp': datetime.now().isoformat(),
                            'type': 'high_frequency_attack',
                            'ip': ip,
                            'attack_type': attack_name,
                            'count': self.suspicious_ips[ip],
                            'sample_request': line.strip()
                        })
        
        except Exception as e:
            # Don't fail on malformed log lines
            pass
    
    def analyze_log_file(self, log_file_path):
        """Analyze an entire log file."""
        try:
            with open(log_file_path, 'r') as f:
                for line in f:
                    self.analyze_log_line(line)
        except FileNotFoundError:
            print(f"Warning: Log file {log_file_path} not found")
        except Exception as e:
            print(f"Error reading log file: {e}")
    
    def generate_report(self):
        """Generate a security report."""
        report = {
            'generated_at': datetime.now().isoformat(),
            'summary': {
                'total_suspicious_ips': len(self.suspicious_ips),
                'total_attack_attempts': sum(self.attack_types.values()),
                'attack_types': dict(self.attack_types)
            },
            'top_attacking_ips': dict(Counter(self.suspicious_ips).most_common(10)),
            'alerts': self.alerts[-50:]  # Last 50 alerts
        }
        return report
    
    def should_block_ip(self, ip, threshold=50):
        """Determine if an IP should be blocked."""
        return self.suspicious_ips.get(ip, 0) > threshold
    
    def get_blocking_recommendations(self):
        """Get IPs that should be blocked."""
        return [ip for ip, count in self.suspicious_ips.items() if count > 20]

def main():
    """Main security monitoring function."""
    monitor = SecurityMonitor()
    
    # Default log locations
    log_files = [
        '/var/log/apache2/access.log',
        '/var/log/nginx/access.log',
        'logs/requests.log',  # Your Flask logs
        'logs/auth.log'
    ]
    
    # Analyze available log files
    for log_file in log_files:
        if Path(log_file).exists():
            print(f"Analyzing {log_file}...")
            monitor.analyze_log_file(log_file)
    
    # Generate and display report
    report = monitor.generate_report()
    
    print("\n" + "="*60)
    print("SECURITY MONITORING REPORT")
    print("="*60)
    print(f"Generated: {report['generated_at']}")
    print(f"Suspicious IPs: {report['summary']['total_suspicious_ips']}")
    print(f"Attack Attempts: {report['summary']['total_attack_attempts']}")
    
    print("\nAttack Types:")
    for attack_type, count in report['summary']['attack_types'].items():
        print(f"  {attack_type}: {count}")
    
    print("\nTop Attacking IPs:")
    for ip, count in report['top_attacking_ips'].items():
        print(f"  {ip}: {count} attempts")
    
    # Blocking recommendations
    block_list = monitor.get_blocking_recommendations()
    if block_list:
        print(f"\nRecommended IP blocks ({len(block_list)} IPs):")
        for ip in block_list[:10]:  # Show top 10
            print(f"  {ip}")
        
        print("\nFirewall rules to add:")
        for ip in block_list[:10]:
            print(f"  ufw deny from {ip}")
    
    # Save detailed report
    with open('security_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\nDetailed report saved to security_report.json")
    
    # Exit with error code if attacks detected
    if report['summary']['total_attack_attempts'] > 0:
        sys.exit(1)
    else:
        print("No security threats detected.")
        sys.exit(0)

if __name__ == "__main__":
    main()