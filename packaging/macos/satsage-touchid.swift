// satsage-touchid — Touch-ID-Hilfsprogramm für SatSage (nur macOS).
//
// Aufruf ohne Argumente. Eingabe: eine JSON-Zeile auf stdin. Ausgabe: eine
// JSON-Zeile auf stdout, Exit 0. Das Passwort steht nie in argv.
//
//   {"v":1,"cmd":"probe"[,"account":"<sha256>"]}
//   {"v":1,"cmd":"enroll","account":"<sha256>","password":"…","reason":"…"}
//   {"v":1,"cmd":"unlock","account":"<sha256>","reason":"…"}
//   {"v":1,"cmd":"remove","account":"<sha256>"}
//
// Antwort: {"ok":true,…} oder {"ok":false,"code":"<code>","message":"…"}.
// Codes: cancelled, failed, not_available, locked_out, invalidated,
// not_found, keychain, error (siehe core/touchid.py).
//
// Ablage: Generic Password im dateibasierten Login-Schlüsselbund (kein
// kSecUseDataProtectionKeychain, daher keine Entitlements nötig).
// Service "SatSage Touch ID", Account = SHA-256 des .env-Pfads.
// kSecAttrGeneric hält LAContext.evaluatedPolicyDomainState vom Aktivieren.
// Ändert sich die Fingerabdruck-Liste, passt der Wert nicht mehr: Eintrag
// wird gelöscht (wie biometryCurrentSet).
//
// Diagnose: Die JSON-Antwort trägt nur Codes (la_name, la_code, osstatus,
// domain_changed). stderr bekommt eine Zeile "satsage-touchid: cmd=… code=…"
// mit denselben Codes. Nie Passwort, Länge, Schlüsselbund-Inhalt,
// DomainState-Bytes oder Account.
//
// Bauen: scripts/build_satsage_macos (swiftc + codesign -s -).

import Foundation
import LocalAuthentication
import Security

let service = "SatSage Touch ID"
let protocolVersion = 1
let maxInputBytes = 64 * 1024

// MARK: - Ausgabe

/// Nur Codes, die auch stderr sehen darf. Wird vor fail() gesetzt.
var diag: [String: Any] = [:]
var currentCommand = "-"

func diagLine(code: String, available: Bool?) -> String {
    var teile = ["cmd=\(currentCommand)", "code=\(code)"]
    if let available = available {
        teile.append("available=\(available ? "ja" : "nein")")
    }
    if let name = diag["la_name"] as? String, let raw = diag["la_code"] as? Int {
        teile.append("la=\(name)(\(raw))")
    }
    if let status = diag["osstatus"] as? Int32 {
        teile.append("osstatus=\(status)")
    }
    if let changed = diag["domain_changed"] as? Bool {
        teile.append("domain_changed=\(changed ? "ja" : "nein")")
    }
    return "satsage-touchid: " + teile.joined(separator: " ") + "\n"
}

func emit(_ object: [String: Any]) -> Never {
    var out = object
    for (key, value) in diag where out[key] == nil {
        out[key] = value
    }
    let code = (out["ok"] as? Bool) == true ? "ok" : (out["code"] as? String ?? "error")
    FileHandle.standardError.write(Data(diagLine(code: code, available: out["available"] as? Bool).utf8))
    out["v"] = protocolVersion
    let data: Data
    if let encoded = try? JSONSerialization.data(withJSONObject: out, options: []) {
        data = encoded
    } else {
        data = Data("{\"ok\":false,\"code\":\"error\",\"message\":\"JSON\"}".utf8)
    }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(0)
}

func fail(_ code: String, _ message: String = "") -> Never {
    emit(["ok": false, "code": code, "message": message])
}

// MARK: - LocalAuthentication

final class EvalResult: @unchecked Sendable {
    var success = false
    var error: Error?
}

func laName(_ code: LAError.Code) -> String {
    switch code {
    case .authenticationFailed: return "authenticationFailed"
    case .userCancel: return "userCancel"
    case .userFallback: return "userFallback"
    case .systemCancel: return "systemCancel"
    case .passcodeNotSet: return "passcodeNotSet"
    case .biometryNotAvailable: return "biometryNotAvailable"
    case .biometryNotEnrolled: return "biometryNotEnrolled"
    case .biometryLockout: return "biometryLockout"
    case .appCancel: return "appCancel"
    case .invalidContext: return "invalidContext"
    case .notInteractive: return "notInteractive"
    default: return "other"
    }
}

/// Fehler → SatSage-Code. Merkt LAError-Name und -Nummer in `diag`.
func mapLAError(_ error: Error?) -> String {
    guard let ns = error as NSError? else { return "error" }
    diag["la_code"] = ns.code
    guard ns.domain == LAErrorDomain, let code = LAError.Code(rawValue: ns.code) else {
        diag["la_name"] = "fremd"
        return "error"
    }
    diag["la_name"] = laName(code)
    switch code {
    case .userCancel, .systemCancel, .appCancel, .userFallback:
        return "cancelled"
    case .authenticationFailed:
        return "failed"
    case .biometryLockout:
        return "locked_out"
    case .biometryNotAvailable, .biometryNotEnrolled, .passcodeNotSet, .notInteractive:
        return "not_available"
    default:
        return "error"
    }
}

/// Fingerabdruck abfragen. Nur Biometrie, kein Mac-Passwort als Ersatz:
/// Der Ausweichweg ist das SatSage-Passwort im Browser.
func evaluateBiometrics(reason: String) -> (LAContext?, String) {
    let context = LAContext()
    context.localizedFallbackTitle = ""
    var canError: NSError?
    guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &canError) else {
        return (nil, mapLAError(canError))
    }
    let result = EvalResult()
    let semaphore = DispatchSemaphore(value: 0)
    context.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, localizedReason: reason) { success, error in
        result.success = success
        result.error = error
        semaphore.signal()
    }
    semaphore.wait()
    if !result.success {
        return (nil, mapLAError(result.error))
    }
    return (context, "")
}

func domainState(_ context: LAContext) -> Data? {
    // Seit macOS 15 als veraltet markiert (Nachfolger domainState.biometry),
    // läuft aber weiter und ist ab macOS 10.11 vorhanden.
    return context.evaluatedPolicyDomainState
}

// MARK: - Schlüsselbund (dateibasiert)

func baseQuery(_ account: String) -> [String: Any] {
    return [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: service,
        kSecAttrAccount as String: account,
    ]
}

@discardableResult
func deleteItem(_ account: String) -> OSStatus {
    return SecItemDelete(baseQuery(account) as CFDictionary)
}

/// Nur Attribute, kein Geheimnis: löst keinen Schlüsselbund-Dialog aus.
func readAttributes(_ account: String) -> (OSStatus, [String: Any]?) {
    var query = baseQuery(account)
    query[kSecReturnAttributes as String] = true
    query[kSecMatchLimit as String] = kSecMatchLimitOne
    var ref: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &ref)
    return (status, ref as? [String: Any])
}

func readSecret(_ account: String) -> (OSStatus, Data?) {
    var query = baseQuery(account)
    query[kSecReturnData as String] = true
    query[kSecMatchLimit as String] = kSecMatchLimitOne
    var ref: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &ref)
    return (status, ref as? Data)
}

func validAccount(_ account: String) -> Bool {
    let hex = Set("0123456789abcdef")
    return account.count == 64 && account.allSatisfy { hex.contains($0) }
}

// MARK: - Befehle

func probe(_ account: String) -> Never {
    let context = LAContext()
    var error: NSError?
    let canEvaluate = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error)
    let touchID = context.biometryType == .touchID
    var out: [String: Any] = [
        "ok": true,
        "available": canEvaluate && touchID,
        "biometry": touchID ? "touchid" : (context.biometryType == LABiometryType.none ? "none" : "other"),
    ]
    if !canEvaluate {
        out["reason"] = mapLAError(error)
    }
    if validAccount(account) {
        let (status, _) = readAttributes(account)
        out["has_item"] = status == errSecSuccess
    }
    emit(out)
}

func enroll(_ account: String, password: String, reason: String) -> Never {
    guard !password.isEmpty else { fail("error", "Passwort fehlt.") }
    let (context, code) = evaluateBiometrics(reason: reason)
    guard let ctx = context else { fail(code) }
    guard let state = domainState(ctx) else { fail("not_available", "DomainState fehlt.") }
    deleteItem(account)
    var add = baseQuery(account)
    add[kSecValueData as String] = Data(password.utf8)
    add[kSecAttrGeneric as String] = state
    add[kSecAttrLabel as String] = "SatSage (Touch ID)"
    add[kSecAttrDescription as String] = "SatSage-Passwort für Touch ID"
    add[kSecAttrComment as String] = "Nur satsage-touchid liest diesen Eintrag, nach Touch ID."
    let status = SecItemAdd(add as CFDictionary, nil)
    diag["osstatus"] = status
    guard status == errSecSuccess else { fail("keychain", "SecItemAdd fehlgeschlagen.") }
    emit(["ok": true])
}

func unlock(_ account: String, reason: String) -> Never {
    let (attrStatus, attributes) = readAttributes(account)
    diag["osstatus"] = attrStatus
    if attrStatus == errSecItemNotFound { fail("not_found") }
    guard attrStatus == errSecSuccess, let attrs = attributes else {
        fail("keychain", "Attribute nicht lesbar.")
    }
    guard let stored = attrs[kSecAttrGeneric as String] as? Data, !stored.isEmpty else {
        diag["domain_changed"] = true
        deleteItem(account)
        fail("invalidated", "DomainState fehlt im Eintrag.")
    }
    let (context, code) = evaluateBiometrics(reason: reason)
    guard let ctx = context else { fail(code) }
    guard let current = domainState(ctx), current == stored else {
        diag["domain_changed"] = true
        diag["osstatus"] = deleteItem(account)
        fail("invalidated", "Fingerabdrücke geändert.")
    }
    diag["domain_changed"] = false
    let (status, secret) = readSecret(account)
    diag["osstatus"] = status
    if status == errSecItemNotFound { fail("not_found") }
    if status == errSecUserCanceled || status == errSecAuthFailed {
        fail("cancelled", "Schlüsselbund-Zugriff abgelehnt.")
    }
    guard status == errSecSuccess, let data = secret, let password = String(data: data, encoding: .utf8) else {
        fail("keychain", "Eintrag nicht lesbar.")
    }
    emit(["ok": true, "password": password])
}

func remove(_ account: String) -> Never {
    let status = deleteItem(account)
    diag["osstatus"] = status
    if status == errSecSuccess { emit(["ok": true]) }
    if status == errSecItemNotFound { fail("not_found") }
    fail("keychain", "Löschen fehlgeschlagen.")
}

// MARK: - Einstieg

guard CommandLine.arguments.count == 1 else {
    fail("error", "Keine Argumente erlaubt; Eingabe nur über stdin.")
}
let input = FileHandle.standardInput.readDataToEndOfFile()
guard !input.isEmpty, input.count <= maxInputBytes,
      let parsed = try? JSONSerialization.jsonObject(with: input, options: []),
      let request = parsed as? [String: Any] else {
    fail("error", "Ungültige Eingabe.")
}
if let version = request["v"] as? Int, version != protocolVersion {
    fail("error", "Protokollversion \(version) nicht unterstützt.")
}
let command = request["cmd"] as? String ?? ""
currentCommand = ["probe", "enroll", "unlock", "remove"].contains(command) ? command : "unbekannt"
let account = request["account"] as? String ?? ""
let reasonText = request["reason"] as? String ?? ""
let reason = reasonText.isEmpty ? "die SatSage-Anmeldung freizugeben" : reasonText

if command == "probe" {
    probe(account)
}
guard validAccount(account) else { fail("error", "Ungültiger Account.") }
switch command {
case "enroll":
    enroll(account, password: request["password"] as? String ?? "", reason: reason)
case "unlock":
    unlock(account, reason: reason)
case "remove":
    remove(account)
default:
    fail("error", "Unbekannter Befehl.")
}
