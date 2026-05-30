# wifi — WiFi hardware tests for the ESP32-P4 / ESP32-C6.
#
# Re-exports the diagnostics entry points so callers can do:
#   from wifi import WiFiDiagnostics, main
from .diag import WiFiDiagnostics, main
