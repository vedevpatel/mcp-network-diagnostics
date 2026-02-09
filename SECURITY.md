# Security Threat Model & Implementation Plan

## Executive Summary

This document outlines the security architecture for MCP Network Diagnostics when deployed in production environments. The current implementation is designed for **trusted, local use** (Claude Desktop on localhost). This plan addresses the security requirements for **public-facing deployments**.

**Current Security Posture:** ⚠️ **NOT PRODUCTION-READY**
- No authentication
- No authorization
- No rate limiting
- Credentials in plaintext YAML files
- No audit logging
- Local stdio transport only

**Target Security Posture:** ✅ **Production-Ready**
- API key authentication with role-based access
- Multi-level authorization (consumer/operator/admin/superuser)
- Rate limiting and abuse prevention
- Encrypted credential storage
- Comprehensive audit logging with tamper detection
- TLS 1.3 transport security

---

## Threat Model

### Assets Under Protection

| Asset | Risk if Compromised | Severity |
|-------|---------------------|----------|
| Device credentials (SSH) | Attacker controls network devices | **CRITICAL** |
| Network topology | Attacker knows infrastructure layout | **HIGH** |
| Agent intents | Attacker manipulates monitoring | **MEDIUM** |
| Command execution | Arbitrary commands on devices | **CRITICAL** |
| Metrics/baselines | Data exfiltration, privacy leak | **MEDIUM** |
| API access | Unauthorized use, abuse, cost | **HIGH** |

### Attack Vectors

| Vector | Threat | Mitigation |
|--------|--------|------------|
| Unauthenticated API access | Anyone can call tools | API keys + auth middleware |
| Credential theft | SSH keys/passwords exposed | Encrypted secrets manager |
| Injection via intent parsing | Malicious intent → command injection | Input validation + sanitization |
| Man-in-the-middle | Traffic interception | TLS 1.3 enforcement |
| Agent abuse | Attacker sets malicious intents | Authorization + audit logging |
| Denial of service | Overwhelm server with requests | Rate limiting + timeouts |
| Privilege escalation | Consumer user gains operator access | Role-based access control |

---

## Security Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         INTERNET                             │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   TRANSPORT SECURITY                         │
│  TLS 1.3 only │ Cert validation │ HTTPS enforcement         │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  AUTHENTICATION LAYER                        │
│  API Keys │ JWT tokens │ OAuth2 (optional) │ mTLS (optional)│
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  AUTHORIZATION LAYER                         │
│  Role-based access │ Tool permissions │ Device ACLs         │
│                                                              │
│  Roles:                                                      │
│    consumer  → check_my_connection, why_is_it_slow, trace   │
│    operator  → + device access, run_command (show only)     │
│    admin     → + set_intent, start_agent, execute_plan      │
│    superuser → + run_command (all), credential management   │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   INPUT VALIDATION                           │
│  Intent sanitization │ Command allowlist │ Param validation │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              RATE LIMITING & ABUSE PREVENTION                │
│  Per-user limits │ Per-endpoint limits │ Cost-based limits  │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                      AUDIT LOGGING                           │
│  Every tool call │ Every auth event │ Tamper-evident chain │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   SECRETS MANAGEMENT                         │
│  Encrypted at rest │ Never logged │ Memory protection       │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)

**Goal:** Basic authentication and authorization

**Deliverables:**
1. API key management system
2. Role-based access control
3. Auth middleware for MCP tools
4. 3 new admin tools: `create_api_key`, `list_api_keys`, `revoke_api_key`

**Files to create:**
- `src/mcp_network/security/__init__.py`
- `src/mcp_network/security/auth.py` - Authentication logic
- `src/mcp_network/security/permissions.py` - RBAC implementation
- `src/mcp_network/security/middleware.py` - Request authentication

**Testing:**
- 15 authentication tests
- 12 authorization tests

### Phase 2: Input Security (Week 2)

**Goal:** Prevent injection attacks and validate all inputs

**Deliverables:**
1. Input validation framework
2. Command allowlisting for `run_command`
3. Intent sanitization
4. Parameter validation

**Files to create:**
- `src/mcp_network/security/validation.py`
- `src/mcp_network/security/commands.py`

**Testing:**
- 10 validation tests
- 8 injection prevention tests

### Phase 3: Rate Limiting & Audit (Week 3)

**Goal:** Prevent abuse and ensure accountability

**Deliverables:**
1. Token bucket rate limiter
2. Comprehensive audit logging
3. Tamper-evident log chain
4. Log verification tools

**Files to create:**
- `src/mcp_network/security/ratelimit.py`
- `src/mcp_network/security/audit.py`

**Testing:**
- 8 rate limiting tests
- 10 audit logging tests

### Phase 4: Secrets & Transport (Week 4)

**Goal:** Protect credentials and communication

**Deliverables:**
1. Encrypted secrets manager
2. TLS configuration
3. Certificate management helpers
4. Secure credential rotation

**Files to create:**
- `src/mcp_network/security/secrets.py`
- `src/mcp_network/security/tls.py`
- `src/mcp_network/security/config.py`

**Testing:**
- 8 secrets management tests
- 5 TLS/transport tests

### Phase 5: Hardening & Testing (Week 5)

**Goal:** Security testing and production readiness

**Deliverables:**
1. Penetration testing suite
2. Security documentation
3. Deployment guide
4. Incident response playbook

**Testing:**
- 20 security integration tests
- Fuzzing tests
- Load testing with auth

---

## Role-Based Access Control (RBAC)

### Role Hierarchy

```
superuser  (full access)
    │
    ├─ admin  (+ agent control, key management)
    │   │
    │   ├─ operator  (+ device access, diagnostics)
    │   │   │
    │   │   └─ consumer  (edge tools only)
```

### Tool Permissions by Role

**Consumer** (Unauthenticated or minimal auth):
- `check_my_connection()`
- `why_is_it_slow(target)`
- `trace_path(target)`
- `run_speedtest()`
- `record_baseline()`
- `compare_to_baseline()`

**Operator** (Read-only device access):
- All consumer tools +
- `list_devices()`
- `get_device_status(device_id)`
- `get_path(src, dst)`
- `diagnose_latency(src, dst)`
- `run_command(device_id, command)` - **show commands only**
- `detect_anomalies()`
- `predict_trends()`

**Admin** (Agent control):
- All operator tools +
- `start_agent()` / `stop_agent()` / `agent_status()`
- `set_intent()` / `list_intents()` / `remove_intent()`
- `get_incidents()`
- `plan_goal()` / `execute_plan()`
- `list_api_keys()` / `revoke_api_key()`

**Superuser** (Full control):
- All admin tools +
- `create_api_key()`
- `run_command(device_id, command)` - **all commands**
- `manage_credentials()`
- `unlock_secrets()`

---

## API Key Format

```
mcp_<key_id>_<secret>
│   │        │
│   │        └─ 32-byte random token (never stored)
│   └─ 8-byte identifier (stored with hash)
└─ Prefix for type identification

Example: mcp_a8f3k2m1_dGVzdC10b2tlbi1zZWNyZXQtZm9yLWV4YW1wbGU
```

**Storage:**
- Only `key_id` and `sha256(secret)` are stored
- Original secret shown **once** during creation
- User must save it securely

**Metadata per key:**
- Role (consumer/operator/admin/superuser)
- Rate limit (requests/minute)
- Expiration date (optional)
- Allowed tools (optional subset)
- Allowed devices (optional subset)
- Description/label

---

## Input Validation Rules

### Device IDs
- Pattern: `^[a-zA-Z0-9_-]{1,64}$`
- No special characters or path traversal

### IP Addresses
- Pattern: `^(?:\d{1,3}\.){3}\d{1,3}$`
- Validate octets 0-255

### Hostnames
- Pattern: `^[a-zA-Z0-9][-a-zA-Z0-9.]{0,253}[a-zA-Z0-9]$`
- RFC 1123 compliant

### Commands
- **Operator role:** Only `show`, `ping`, `traceroute`, `display`
- **Superuser role:** All commands (but logged)
- Reject shell metacharacters: `; & | \` $ ( ) < > \n`
- No path traversal: `../`

### Natural Language Intents
- Max length: 500 characters
- No shell metacharacters
- No template injection patterns: `{{ }}`, `${ }`
- No XSS: `<script>`, `javascript:`

---

## Rate Limiting

### Per-Key Limits (Token Bucket)

| Role | Requests/Minute | Burst |
|------|-----------------|-------|
| Consumer | 60 | 10 |
| Operator | 120 | 20 |
| Admin | 300 | 50 |
| Superuser | 600 | 100 |

### Global Limits
- 1000 requests/minute total
- 10,000 requests/hour total
- Automatic backoff on repeated auth failures

### Cost-Based Limits (Future)
- Track "credits" per operation
- Expensive ops: `run_command` (10 credits), `diagnose_latency` (5 credits)
- Cheap ops: `get_device_status` (1 credit), `list_devices` (1 credit)

---

## Audit Logging

### Logged Events

**Authentication:**
- Successful auth (key_id, role, IP)
- Failed auth (attempted key, IP, reason)
- Key creation/revocation
- Secrets unlock/lock

**Tool Calls:**
- Tool name
- Parameters (sanitized - no credentials)
- Result (success/error)
- Duration (ms)
- User (key_id, role)

**Configuration Changes:**
- Intent added/removed
- Agent started/stopped
- Credentials updated

### Log Format (JSONL)

```json
{
  "timestamp": 1738976543.123,
  "event_type": "tool_call",
  "key_id": "a8f3k2m1",
  "role": "operator",
  "tool": "diagnose_latency",
  "parameters": {"src": "R1", "dst": "R5"},
  "result": "success",
  "duration_ms": 1234.5,
  "client_ip": "203.0.113.42",
  "previous_hash": "abc123...",
  "event_hash": "def456..."
}
```

### Tamper Detection

Each log entry includes:
1. Hash of previous entry (`previous_hash`)
2. Hash of current entry (`event_hash`)

Forms a blockchain-like chain. Tampering with any entry breaks the chain.

**Verification:**
```bash
mcp-network verify-audit-log ~/.mcp_network/audit/audit_20260208.jsonl
✓ Chain integrity verified (1,234 events)
```

---

## Secrets Management

### Encryption

- **Algorithm:** AES-256-GCM via Fernet (symmetric encryption)
- **Key derivation:** PBKDF2-HMAC-SHA256, 480,000 iterations
- **Master password:** User-provided, never stored
- **Salt:** 16 random bytes, stored alongside encrypted file

### Storage Format

```
~/.mcp_network/
├── secrets.enc        # Encrypted credentials (600 permissions)
├── secrets.salt       # Salt for key derivation (600 permissions)
└── secrets.lock       # Prevents concurrent access
```

### Workflow

```python
# Unlock once per session
mgr = SecretsManager()
mgr.unlock("my-master-password")

# Use credentials
creds = mgr.get_credential("router-1")
ssh_client.connect(host, username=creds["username"], password=creds["password"])

# Lock when done
mgr.lock()
```

### Credential Rotation

```bash
# Rotate a device password
mcp-network rotate-credential router-1 \
  --old-password "old_pass" \
  --new-password "new_pass"

# Automatically:
# 1. Connects to device with old password
# 2. Changes password on device
# 3. Updates encrypted storage
# 4. Logs rotation event
```

---

## TLS Configuration

### Production (Let's Encrypt)

```yaml
# config.yaml
server:
  host: 0.0.0.0
  port: 443
  tls:
    enabled: true
    cert_file: /etc/letsencrypt/live/example.com/fullchain.pem
    key_file: /etc/letsencrypt/live/example.com/privkey.pem
    min_version: TLSv1.3
```

### Development (Self-Signed)

```bash
mcp-network generate-cert --output ~/.mcp_network/certs/
```

```yaml
# config.yaml
server:
  host: 127.0.0.1
  port: 8443
  tls:
    enabled: true
    cert_file: ~/.mcp_network/certs/server.crt
    key_file: ~/.mcp_network/certs/server.key
```

---

## Deployment Security Checklist

### Pre-Deployment

- [ ] All API endpoints require authentication
- [ ] TLS 1.3 enabled with valid certificate
- [ ] API keys generated and distributed securely
- [ ] Device credentials encrypted with strong master password
- [ ] Rate limiting configured
- [ ] Audit logging enabled
- [ ] Input validation on all parameters
- [ ] Command allowlist configured
- [ ] File permissions set (600 on secrets)
- [ ] Security headers configured (HSTS, CSP, etc.)

### Post-Deployment

- [ ] Verify TLS with `ssllabs.com` scan (A+ rating)
- [ ] Test authentication with invalid keys
- [ ] Test authorization with lower-privilege keys
- [ ] Verify rate limiting triggers
- [ ] Verify audit log chain integrity
- [ ] Test credential rotation
- [ ] Review audit logs for anomalies
- [ ] Set up monitoring alerts for auth failures

### Ongoing

- [ ] Rotate API keys every 90 days
- [ ] Rotate device credentials every 180 days
- [ ] Review audit logs weekly
- [ ] Update TLS certificates before expiration
- [ ] Apply security patches within 7 days
- [ ] Conduct security audits quarterly

---

## Incident Response Playbook

### Suspected API Key Compromise

1. **Immediate:** Revoke compromised key
   ```bash
   mcp-network revoke-api-key <key_id>
   ```

2. **Investigate:** Review audit logs for unauthorized access
   ```bash
   mcp-network audit-search --key-id <key_id> --last 7d
   ```

3. **Contain:** Check for unauthorized intent creation or agent abuse

4. **Remediate:** Issue new key to legitimate user

5. **Post-incident:** Review key distribution process

### Suspected Device Credential Theft

1. **Immediate:** Rotate affected credentials
   ```bash
   mcp-network rotate-credential <device_id> --force
   ```

2. **Investigate:** Review audit logs for suspicious commands

3. **Contain:** Check device logs for unauthorized access

4. **Remediate:** Update secrets manager password if compromised

5. **Post-incident:** Enable MFA on devices if supported

### Denial of Service Attack

1. **Immediate:** Enable aggressive rate limiting
   ```yaml
   rate_limiting:
     global: 100  # Reduce from 1000
   ```

2. **Investigate:** Identify attacking IPs in audit logs

3. **Contain:** Block IPs at firewall level

4. **Remediate:** Restore normal rate limits after attack subsides

5. **Post-incident:** Consider adding IP allowlist

---

## Security Testing Strategy

### Unit Tests (88 tests total)

- Authentication: 15 tests
- Authorization: 12 tests
- Input validation: 10 tests
- Injection prevention: 8 tests
- Rate limiting: 8 tests
- Audit logging: 10 tests
- Secrets management: 8 tests
- TLS/transport: 5 tests
- Integration: 12 tests

### Penetration Testing

**Tools:**
- OWASP ZAP for API security
- SQLMap for injection testing
- Nikto for web vulnerabilities
- Custom fuzzing scripts

**Scenarios:**
- [ ] Auth bypass attempts
- [ ] Privilege escalation
- [ ] Command injection via intents
- [ ] SQL injection (if using SQL in future)
- [ ] XSS via intent display
- [ ] Path traversal in device IDs
- [ ] Rate limit evasion
- [ ] Audit log tampering

### Load Testing with Security

```bash
# Generate 1000 concurrent authenticated requests
ab -n 10000 -c 1000 \
   -H "Authorization: Bearer mcp_<key>" \
   https://localhost:8443/check_my_connection
```

Verify:
- Rate limiting triggers correctly
- Auth doesn't degrade under load
- Audit logs remain consistent
- No credential leaks in errors

---

## Future Enhancements

### Short-term (3-6 months)
- [ ] OAuth2 integration (Google, GitHub SSO)
- [ ] Mutual TLS (mTLS) for device authentication
- [ ] API key scopes (fine-grained permissions)
- [ ] IP allowlist/blocklist
- [ ] Webhook notifications for security events

### Medium-term (6-12 months)
- [ ] Multi-factor authentication (TOTP)
- [ ] Hardware security module (HSM) integration
- [ ] Federated identity (SAML)
- [ ] Cost-based rate limiting
- [ ] Anomaly detection in API usage patterns

### Long-term (12+ months)
- [ ] Zero-trust architecture
- [ ] Runtime application self-protection (RASP)
- [ ] Automated threat intelligence integration
- [ ] SOC 2 Type II compliance
- [ ] FIPS 140-2 certification

---

## Security Contacts

**Report a vulnerability:**
- Email: security@example.com
- PGP Key: [Link to public key]
- Response time: 24 hours

**Security updates:**
- Subscribe: security-announce@example.com
- RSS: https://example.com/security.xml

**Bug bounty:**
- Platform: HackerOne
- Scope: All production systems
- Rewards: $100-$5000 based on severity

---

## Compliance & Standards

This implementation aims to meet:

- [ ] OWASP Top 10 (2021)
- [ ] NIST Cybersecurity Framework
- [ ] CIS Controls v8
- [ ] SOC 2 Type II (future)
- [ ] GDPR (for EU users)
- [ ] CCPA (for California users)

---

## References

- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [CWE Top 25 Most Dangerous Software Weaknesses](https://cwe.mitre.org/top25/)
- [Fernet Specification](https://github.com/fernet/spec/)
- [Token Bucket Algorithm](https://en.wikipedia.org/wiki/Token_bucket)
