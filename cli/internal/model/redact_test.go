package model

import (
	"strings"
	"testing"
)

func TestRedactCredentials(t *testing.T) {
	for _, testCase := range []struct {
		name, text, secret string
	}{
		{"inline user:pass", "could not reach postgresql://orders:hunter2-r@db/orders today", "hunter2-r"},
		{"query-string password", "dsn https://db.example.com/x?user=a&password=hunter2-q&ssl=1", "hunter2-q"},
		{"a PEM block", "key -----BEGIN PRIVATE KEY-----\nMIIEvQhunter2pem\n-----END PRIVATE KEY----- end", "hunter2pem"},
		{"a provider key", "token sk-ABCDEFGHIJKLMNOPQRSTUVWX leaked", "sk-ABCDEFGHIJKLMNOPQRSTUVWX"},
		{"an anthropic key", "key sk-ant-api03-ABCDEFGHIJ_KLMNOPQRST-uv leaked", "ABCDEFGHIJ_KLMNOPQRST"},
		{"a JWT", "bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig", "eyJhbGciOiJIUzI1NiJ9"},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			if !LooksLikeCredential(testCase.text) {
				t.Fatalf("not recognised as credential-shaped: %q", testCase.text)
			}
			redacted := RedactCredentials(testCase.text)
			if strings.Contains(redacted, testCase.secret) || !strings.Contains(redacted, "[redacted]") {
				t.Errorf("RedactCredentials(%q) = %q", testCase.text, redacted)
			}
		})
	}
	for _, clean := range []string{
		"no docker-compose file found",
		"postgresql+asyncpg://localhost:5432/culprit-intent-placeholder",
		"the values of 7 key(s) were not captured — only their shape",
	} {
		if LooksLikeCredential(clean) {
			t.Errorf("an ordinary reason was treated as a credential: %q", clean)
		}
	}
}
