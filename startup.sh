#!/bin/bash
# startup.sh - configures ~/jesus/run.sh to run in a terminal on login
# Supports macOS and Linux

set -e

RUN_SCRIPT="$HOME/jesus/run.sh"
WRAPPER="$HOME/.jesus_startup_wrapper.sh"
OS="$(uname -s)"

# --- Create wrapper script ---

if [ "$OS" = "Darwin" ]; then
    cat > "$WRAPPER" << 'EOF'
#!/bin/bash
osascript -e 'tell application "Terminal" to do script "bash ~/jesus/run.sh"'
EOF

elif [ "$OS" = "Linux" ]; then
    # Find an available terminal emulator
    FOUND_TERM=""
    for term in x-terminal-emulator gnome-terminal xterm konsole xfce4-terminal lxterminal mate-terminal; do
        if command -v "$term" &>/dev/null; then
            FOUND_TERM="$term"
            break
        fi
    done

    if [ -z "$FOUND_TERM" ]; then
        echo "ERROR: No terminal emulator found. Install xterm or another terminal."
        exit 1
    fi

    case "$FOUND_TERM" in
        gnome-terminal)
            TERM_CMD="gnome-terminal -- bash -c 'bash ~/jesus/run.sh; exec bash'"
            ;;
        *)
            TERM_CMD="$FOUND_TERM -e bash -c 'bash ~/jesus/run.sh; exec bash'"
            ;;
    esac

    cat > "$WRAPPER" << EOF
#!/bin/bash
$TERM_CMD
EOF

else
    echo "Unsupported OS: $OS"
    exit 1
fi

chmod +x "$WRAPPER"

# --- Install startup entry ---

if [ "$OS" = "Darwin" ]; then
    PLIST="$HOME/Library/LaunchAgents/com.user.jesus.plist"
    mkdir -p "$(dirname "$PLIST")"

    cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.jesus</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$WRAPPER</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

    # Load the agent (try both old and new launchctl syntax)
    launchctl load "$PLIST" 2>/dev/null || launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    echo "macOS: LaunchAgent installed at $PLIST"

elif [ "$OS" = "Linux" ]; then
    DESKTOP="$HOME/.config/autostart/jesus.desktop"
    mkdir -p "$(dirname "$DESKTOP")"

    cat > "$DESKTOP" << EOF
[Desktop Entry]
Type=Application
Name=Jesus Startup
Exec=$WRAPPER
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF

    echo "Linux: Autostart entry installed at $DESKTOP"
fi

echo "Done. ~/jesus/run.sh will launch in a terminal on next login."
