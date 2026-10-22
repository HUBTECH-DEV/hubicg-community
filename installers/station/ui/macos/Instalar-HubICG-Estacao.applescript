-- Entrada AppleScript alternativa. A ponte JXA usa os mesmos diálogos Standard Additions.
on run argv
    if (count argv) < 1 then error "Informe a pasta macos da GUI como primeiro argumento."
    set guiDir to item 1 of argv
    set commandText to "/usr/bin/osascript -l JavaScript " & quoted form of (guiDir & "/HubICG-Station-UI.js") & " " & quoted form of guiDir
    repeat with i from 2 to (count argv)
        set commandText to commandText & " " & quoted form of (item i of argv)
    end repeat
    return do shell script commandText
end run
