// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package probe

import (
	"context"
	"time"
)

// Timer times one GET on a fresh connection. RealHTTPClient implements it;
// an HTTPClient that does not (a test fake) cannot take a latency sample,
// and the probe says so.
type Timer interface {
	TimeGet(ctx context.Context, url string, timeout time.Duration) (Timing, error)
}
