#cloud-config
# Bootstraps a fresh Ubuntu 24.04 host into a ZapAgent app server.
# Runs once on first boot.

package_update: true
package_upgrade: true
packages:
  - ca-certificates
  - curl
  - git
  - ufw
  - fail2ban

write_files:
  - path: /opt/zapagent/.env
    permissions: "0600"
    owner: root:root
    content: |
      ${indent(6, env_blob)}

  - path: /etc/systemd/system/zapagent.service
    permissions: "0644"
    content: |
      [Unit]
      Description=ZapAgent Docker Compose stack
      Requires=docker.service
      After=docker.service network-online.target

      [Service]
      Type=oneshot
      RemainAfterExit=yes
      WorkingDirectory=/opt/zapagent/repo
      ExecStart=/usr/bin/docker compose --env-file /opt/zapagent/.env up -d
      ExecStop=/usr/bin/docker compose down

      [Install]
      WantedBy=multi-user.target

runcmd:
  - install -m 0755 -d /etc/apt/keyrings
  - curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  - chmod a+r /etc/apt/keyrings/docker.asc
  - >-
    echo "deb [arch=$(dpkg --print-architecture)
    signed-by=/etc/apt/keyrings/docker.asc]
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable"
    | tee /etc/apt/sources.list.d/docker.list > /dev/null
  - apt-get update
  - apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  - ufw default deny incoming
  - ufw default allow outgoing
  - ufw allow 22/tcp
  - ufw allow 80/tcp
  - ufw allow 443/tcp
  - ufw --force enable
  - systemctl enable --now fail2ban
  - mkdir -p /opt/zapagent
  - git clone --depth 1 --branch ${git_ref} ${repo_url} /opt/zapagent/repo
  - systemctl daemon-reload
  - systemctl enable --now zapagent.service
