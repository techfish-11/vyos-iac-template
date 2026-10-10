/* Example only: replace addresses and public key with your device's configuration.
   Keep every existing setting that the device needs: apply replaces the whole config.
   Guide: docs/learning.md. */
interfaces {
    ethernet eth0 {
        address "192.0.2.1/24"
        description "Management"
    }
    ethernet eth1 {
        address "198.51.100.1/24"
        description "LAN"
    }
    loopback lo {
    }
}
protocols {
    static {
        route 0.0.0.0/0 {
            next-hop 192.0.2.254 {
            }
        }
    }
}
service {
    ntp {
        server 192.0.2.123 {
        }
    }
    ssh {
        port 22
        disable-password-authentication
    }
}
system {
    host-name "router01"
    config-management {
        commit-revisions 100
        commit-confirm {
            action reload
        }
    }
    login {
        user automation {
            authentication {
                public-keys operator {
                    type "ssh-ed25519"
                    key "AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                }
            }
        }
    }
    name-server "192.0.2.53"
    time-zone "Asia/Tokyo"
    syslog {
        global {
            facility all {
                level info
            }
        }
    }
}
