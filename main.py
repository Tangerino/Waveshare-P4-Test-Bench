# main.py — boot entry point. Top-level hardware test selector.
#
# Add new hardware by dropping a package next to wifi/ and eth/ (each exposing
# a main() menu), then add a line below.
#
# After exit, the last-used diagnostics object is returned at the REPL.

MENU = """
==== ESP32-P4 Hardware Tests ====
 1) WiFi  (ESP32-C6, hosted RPC)
 2) Ethernet (IP101 PHY, RMII)
 3) System (CPU / memory / flash)
 4) microSD (SDMMC)
 5) I2C bus scan
 6) Sleep / wake
 7) Audio (ES8311 speaker)
 8) GPIO (blink/read any pin)
 9) Serial loopback (4 UARTs, HW)
10) BLE (ESP32-C6, hosted)
11) Threads (dual-core, IPC, perf)
 0) Exit
Choose: """


def select():
    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
            print()
            return
        if choice == '1':
            import wifi

            wifi.main()
        elif choice == '2':
            import eth

            eth.main()
        elif choice == '3':
            import system

            system.main()
        elif choice == '4':
            import sdcard

            sdcard.main()
        elif choice == '5':
            import i2c

            i2c.main()
        elif choice == '6':
            import sleep

            sleep.main()
        elif choice == '7':
            import audio

            audio.main()
        elif choice == '8':
            import gpio

            gpio.main()
        elif choice == '9':
            import serial

            serial.main()
        elif choice == '10':
            import ble

            ble.main()
        elif choice == '11':
            import thread

            thread.main()
        elif choice == '0':
            return
        else:
            print('?')


# If we just woke from a deep-sleep test, report it before showing the menu.
try:
    import sleep

    sleep.check_wake()
except Exception:
    pass

# Ctrl-C from any menu propagates here and drops cleanly to the REPL — this is
# also what lets `mpremote`/deploy.sh interrupt the menu to upload files.
try:
    select()
except KeyboardInterrupt:
    print()
