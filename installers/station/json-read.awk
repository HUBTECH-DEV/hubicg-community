# Dependency-free JSON reader for the station engine (POSIX awk, LC_ALL=C).
# Validates the entire document; get returns one scalar without evaluating it.
# answers mode additionally validates the envelope and the known answer types.
function fail() { bad = 1; exit 2 }
function ws() { while (substr(doc, pos, 1) ~ /^[ \t\r\n]$/) pos++ }
function component(key) {
    # JSON Pointer escaping keeps a literal slash in an unknown key from
    # becoming a path separator (and avoids collisions with literal tildes).
    gsub(/~/, "~0", key); gsub(/\//, "~1", key)
    return key
}
function quoted(text,    i,c,out) {
    out = "\""
    for (i = 1; i <= length(text); i++) {
        c = substr(text, i, 1)
        if (c ~ /[[:cntrl:]]/) fail()
        if (c == "\\" || c == "\"") out = out "\\"
        out = out c
    }
    return out "\""
}
function hex4(    s,i,n,c) {
    s = substr(doc, pos, 4)
    if (length(s) != 4 || s ~ /[^0-9a-fA-F]/) fail()
    n = 0
    for (i = 1; i <= 4; i++) {
        c = index("0123456789abcdef", tolower(substr(s, i, 1))) - 1
        n = n * 16 + c
    }
    pos += 4
    return n
}
function utf8(n) {
    # NUL cannot be represented by shell variables: reject it, never truncate.
    if (n == 0 || n > 1114111) fail()
    if (n < 128) return sprintf("%c", n)
    if (n < 2048) return sprintf("%c%c", 192 + int(n/64), 128 + n%64)
    if (n < 65536) return sprintf("%c%c%c", 224 + int(n/4096), 128 + int(n/64)%64, 128 + n%64)
    return sprintf("%c%c%c%c", 240 + int(n/262144), 128 + int(n/4096)%64, 128 + int(n/64)%64, 128 + n%64)
}
function string(    out,c,e,n,low) {
    if (substr(doc, pos++, 1) != "\"") fail()
    out = ""
    while (pos <= length(doc)) {
        c = substr(doc, pos++, 1)
        if (c == "\"") return out
        if (c ~ /[[:cntrl:]]/) fail()
        if (c != "\\") { out = out c; continue }
        e = substr(doc, pos++, 1)
        if (e == "\"" || e == "\\" || e == "/") out = out e
        else if (e == "b") out = out sprintf("%c", 8)
        else if (e == "f") out = out sprintf("%c", 12)
        else if (e == "n") out = out "\n"
        else if (e == "r") out = out "\r"
        else if (e == "t") out = out "\t"
        else if (e == "u") {
            n = hex4()
            if (n >= 55296 && n <= 56319) {
                if (substr(doc, pos, 2) != "\\u") fail()
                pos += 2; low = hex4()
                if (low < 56320 || low > 57343) fail()
                n = 65536 + (n - 55296)*1024 + low - 56320
            } else if (n >= 56320 && n <= 57343) fail()
            out = out utf8(n)
        } else fail()
    }
    fail()
}
function value(path, depth,    c,k,child,n,token,kind,scalar) {
    if (depth > 64) fail()
    ws(); c = substr(doc, pos, 1); scalar = ""
    if (c == "{") {
        kind = "object"; pos++; ws()
        if (substr(doc, pos, 1) == "}") pos++
        else while (1) {
            ws(); k = string(); child = path "/" component(k)
            if (seen[child]++) fail()
            ws(); if (substr(doc, pos++, 1) != ":") fail()
            value(child, depth + 1); ws(); c = substr(doc, pos++, 1)
            if (c == "}") break
            if (c != ",") fail()
        }
    } else if (c == "[") {
        kind = "array"; pos++; ws(); n = 0
        if (substr(doc, pos, 1) == "]") pos++
        else while (1) {
            value(path "/[" n++ "]", depth + 1); ws(); c = substr(doc, pos++, 1)
            if (c == "]") break
            if (c != ",") fail()
        }
    } else if (c == "\"") { kind = "string"; scalar = string() }
    else if (substr(doc, pos, 4) == "true") { kind = "boolean"; scalar = "true"; pos += 4 }
    else if (substr(doc, pos, 5) == "false") { kind = "boolean"; scalar = "false"; pos += 5 }
    else if (substr(doc, pos, 4) == "null") { kind = "null"; pos += 4 }
    else {
        token = substr(doc, pos)
        if (!match(token, /^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?/)) fail()
        kind = "number"; scalar = substr(token, 1, RLENGTH); pos += RLENGTH
    }
    types[path] = kind; values[path] = scalar
}
{ doc = doc $0 "\n" }
END {
    if (bad) exit 2
    pos = 1; value("", 0); ws()
    if (pos <= length(doc) || types[""] != "object") fail()
    if (mode == "auth") {
        # Account email/org never leave memory, even through a temporary file.
        if (types["/loggedIn"] != "boolean") fail()
        out = "{\"loggedIn\":" values["/loggedIn"]
        if (types["/authMethod"] == "string") out = out ",\"authMethod\":" quoted(values["/authMethod"])
        if (types["/configDirectory"] == "string") out = out ",\"configDirectory\":" quoted(values["/configDirectory"])
        print out "}"
        exit 0
    }
    if (mode == "answers" || mode == "warnings") {
        if (types["/schema"] != "string" || values["/schema"] != "hubicg.station.answers/1" || types["/answers"] != "object") fail()
        expected["git.name"] = expected["git.email"] = "string"
        expected["desktop.loginConfirmed"] = expected["git.useSystemCertStore"] = expected["claude.addToPath"] = "boolean"
        for (k in expected) if (("/answers/" k) in types) {
            if (types["/answers/" k] != expected[k]) fail()
            if (expected[k] == "string" && values["/answers/" k] ~ /[[:cntrl:]]/) fail()
        }
        if (mode == "warnings") {
            for (path in types) if (path ~ /^\/answers\//) {
                k = substr(path, 10)
                if (!(k in expected)) { print "chaves-desconhecidas"; break }
            }
            exit 0
        }
        key = "/answers/" key
    }
    if (required_type != "" && types[key] != required_type) exit 2
    if (key in values) printf "%s", values[key]
}
