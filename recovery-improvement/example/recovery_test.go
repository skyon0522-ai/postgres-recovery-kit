package main

import (
	"context"
	"testing"
	"time"

	toxiproxy "github.com/Shopify/toxiproxy/v2/client"
	pg "github.com/go-pg/pg/v10"
)

// TestDurableRecovery extends the copied example's proxy and go-pg connection path.
// The keyed INSERT is intentionally scoped; this does not prove general exactly-once delivery.
func TestDurableRecovery(t *testing.T) {
	direct := connectDB(recoveryEndpoint("RECOVERY_PG_ADDR"))
	via := connectDB(recoveryEndpoint("RECOVERY_PROXY_ADDR"))
	defer direct.Close()
	defer via.Close()
	proxy := proxies["postgresql"]
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	waitForRecovery := func() {
		t.Helper()
		start := time.Now()
		ctx, cancel := context.WithDeadline(context.Background(), start.Add(5*time.Second))
		defer cancel()
		for err := via.Ping(ctx); err != nil; err = via.Ping(ctx) {
			if time.Since(start) >= 5*time.Second {
				t.Fatalf("same pool did not recover within deadline: %v", err)
			}
			time.Sleep(50 * time.Millisecond)
		}
		if time.Since(start) >= 5*time.Second {
			t.Fatal("same pool recovery completed after the five-second acceptance deadline")
		}
		t.Logf("same pool recovered after %s", time.Since(start))
	}
	_, err := direct.Exec(`CREATE TABLE recovery_writes (operation_key text PRIMARY KEY, payload text NOT NULL)`)
	must(err)
	write := func(db *pg.DB, key string) (pg.Result, error) {
		return db.Exec(`INSERT INTO recovery_writes VALUES (?, ?) ON CONFLICT (operation_key) DO NOTHING`, key, "value:"+key)
	}
	assertRow := func(db *pg.DB, key string, want int) {
		t.Helper()
		var count int
		var payload string
		_, err := db.QueryOne(pg.Scan(&count, &payload), `SELECT count(*), COALESCE(max(payload), '') FROM recovery_writes WHERE operation_key = ?`, key)
		must(err)
		if count != want || (want == 1 && payload != "value:"+key) {
			t.Fatalf("%s: count=%d payload=%q, wanted count=%d and matching payload", key, count, payload, want)
		}
		t.Logf("row %s: count=%d payload=%q", key, count, payload)
	}
	result, err := write(via, "before-outage")
	must(err)
	if result.RowsAffected() != 1 {
		t.Fatal("initial write did not insert one row")
	}
	must(proxy.Disable())
	t.Cleanup(func() {
		if !proxy.Enabled {
			if err := proxy.Enable(); err != nil {
				t.Errorf("restore proxy: %v", err)
			}
		}
	})
	if err := via.Ping(context.Background()); err == nil {
		t.Fatal("disabled proxy allowed connection")
	} else {
		t.Logf("connection failed during outage: %v", err)
	}
	if _, err := write(via, "during-outage"); err == nil {
		t.Fatal("disabled proxy allowed write")
	} else {
		t.Logf("write failed during outage: %v", err)
	}
	assertRow(direct, "during-outage", 0)
	must(proxy.Enable())
	waitForRecovery() // Recover with the same DB object, not a replacement pool.
	result, err = write(via, "after-outage")
	must(err)
	if result.RowsAffected() != 1 {
		t.Fatal("restored proxy did not insert one row")
	}
	assertRow(via, "before-outage", 1)
	assertRow(via, "after-outage", 1)
	_, err = proxy.AddToxic("lost_ack", "timeout", "downstream", 1, toxiproxy.Attributes{"timeout": 0})
	must(err)
	toxicPresent := true
	t.Cleanup(func() {
		if toxicPresent {
			if err := proxy.RemoveToxic("lost_ack"); err != nil {
				t.Errorf("remove toxic: %v", err)
			}
		}
	})
	start := time.Now()
	if _, err := write(via, "lost-ack"); err == nil {
		t.Fatal("dropped acknowledgement unexpectedly succeeded")
	} else {
		t.Logf("write acknowledgement lost after %s: %v", time.Since(start), err)
	}
	assertRow(direct, "lost-ack", 1) // Establish that the write committed despite the client error.
	must(proxy.RemoveToxic("lost_ack"))
	toxicPresent = false
	waitForRecovery()
	result, err = write(via, "lost-ack")
	must(err)
	if result.RowsAffected() != 0 {
		t.Fatalf("keyed retry inserted %d rows, wanted zero", result.RowsAffected())
	}
	t.Log("same-key retry affected zero rows")
	assertRow(via, "lost-ack", 1)
	var total int
	_, err = via.QueryOne(pg.Scan(&total), `SELECT count(*) FROM recovery_writes`)
	must(err)
	if total != 3 {
		t.Fatalf("total rows=%d, wanted 3", total)
	}
}
