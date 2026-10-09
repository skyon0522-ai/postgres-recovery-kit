package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"testing"
	"time"

	toxiproxy "github.com/Shopify/toxiproxy/v2/client"
	pg "github.com/go-pg/pg/v10"
)

var db *pg.DB
var toxi *toxiproxy.Client
var proxies map[string]*toxiproxy.Proxy

func DB() *pg.DB {
	if db == nil {
		var err error
		db, err = setupDB(recoveryEndpoint("RECOVERY_PROXY_ADDR"), "sample_test")
		if err != nil {
			log.Panicf("Could not connect to DB: %+v", err)
		}
	}
	return db
}

func connectDB(addr string) *pg.DB {
	return pg.Connect(&pg.Options{
		Addr:     addr,
		User:     "postgres",
		Database: "sample_test",
		PoolSize: 1, MaxRetries: 0,
		DialTimeout: time.Second, ReadTimeout: time.Second, WriteTimeout: time.Second,
	})
}

func init() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)
	fmt.Println("=== SETUP")
	runToxiproxyServer()
	populateProxies()
}

func populateProxies() {
	if toxi == nil {
		toxi = toxiproxy.NewClient(recoveryEndpoint("RECOVERY_TOXI_ADDR"))
	}

	var err error
	_, err = toxi.Populate([]toxiproxy.Proxy{{
		Name:     "postgresql",
		Listen:   recoveryEndpoint("RECOVERY_PROXY_ADDR"),
		Upstream: recoveryEndpoint("RECOVERY_PG_ADDR"),
		Enabled:  true,
	}})
	if err != nil {
		panic(err)
	}

	proxies, err = toxi.Proxies()
	if err != nil {
		panic(err)
	}
}

func runToxiproxyServer() {
	// minimalism: the isolated runner owns the copied server process and its cleanup.
	conn, err := net.DialTimeout("tcp", recoveryEndpoint("RECOVERY_TOXI_ADDR"), time.Second)
	if err != nil {
		panic(err)
	}
	conn.Close()
}

func recoveryEndpoint(name string) string {
	addr := os.Getenv(name)
	host, port, err := net.SplitHostPort(addr)
	if err != nil || host != "127.0.0.1" || port == "" {
		panic(name + " must identify an explicit synthetic fixture on 127.0.0.1")
	}
	return addr
}

func TestSlowDBConnection(t *testing.T) {
	db := DB()

	// Add 1s latency to 100% of downstream connections
	proxies["postgresql"].AddToxic("latency_down", "latency", "downstream", 1.0, toxiproxy.Attributes{
		"latency": 10000,
	})
	defer proxies["postgresql"].RemoveToxic("latency_down")

	err := process(db)
	if err != nil {
		t.Fatalf("got error %v, wanted no errors", err)
	}
}

func TestOutageResetPeer(t *testing.T) {
	db := DB()

	// Add broken TCP connection
	proxies["postgresql"].AddToxic("reset_peer_down", "reset_peer", "downstream", 1.0, toxiproxy.Attributes{
		"timeout": 10,
	})
	defer proxies["postgresql"].RemoveToxic("reset_peer_down")

	err := process(db)
	if err == nil {
		t.Fatalf("expect error")
	}
}
