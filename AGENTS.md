# TalentMAP — State Department Bureau of Diplomatic Technology

TalentMAP is the Foreign Service assignment and bidding system. It handles sensitive personnel data for ~13,000 Foreign Service Officers and integrates with FSBid (the downstream bidding engine) via SOAP/HTTP.

## Security

- All database queries must use parameterized statements (no string interpolation)
- All API endpoints must validate authentication via SAML2 or token middleware
- PII fields (employee IDs, names, post assignments) must never appear in logs
- All external API calls must use TLS 1.2+ with certificate validation
- Session tokens must expire after 15 minutes of inactivity
- All cryptographic operations must use FIPS 140-2 validated algorithms
- No sensitive data in URL parameters — use request body or headers
- Hash all employee identifiers before writing to log files

## Architecture

- All FSBid integration must go through the typed client (no raw requests.get/post)
- All API responses must be validated against typed models before use
- All new endpoints must include permission_classes declaration
- Error responses must use generic messages (no stack traces to client)
- External service calls must implement retry with exponential backoff
- Circuit breaker pattern required for all third-party integrations
- Use dependency injection for external service clients (testability)

## Testing

- All new code must include unit tests with >80% branch coverage
- Integration tests must use mocked FSBid responses (no live calls in CI)
- Security-sensitive code paths require explicit test for unauthorized access
- All PII-handling code requires test proving no PII leaks to logs
- Functional parity tests required for any integration refactor

## Compliance

- Map all security-relevant code changes to NIST 800-53 control families
- Document STIG control IDs on all security remediations
- All third-party dependencies must be checked against NVD before introduction
- Maintain audit trail for all data access (who, what, when)
