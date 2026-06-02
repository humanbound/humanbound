---
description: "Deployment options for Humanbound — local engine, managed platform, and air-gapped variants for organisations with specific security and compliance needs."
title: Deployment
keywords:
  - humanbound deployment
  - SaaS deployment
  - on-premises Humanbound
  - private cloud
  - data sovereignty
  - SOC 2 deployment
  - air-gapped deployment
  - on-prem AI security
---

# Deployment Options

Humanbound is available in three deployment models: SaaS (managed cloud, data stored in the EU North Europe region on SOC 2 compliant infrastructure), on-premises (Azure Functions runtime with PostgreSQL/Cosmos DB, deployed inside your network for full data sovereignty), and private cloud (dedicated Humanbound instance in your Azure or AWS tenant, managed by the Humanbound team). The sections below compare features and link to setup.

## SaaS (Cloud)

The default deployment. Humanbound hosts and manages everything.

- **No infrastructure to manage** -- get started immediately
- Automatic updates and scaling
- Data stored in EU (North Europe region)
- SOC 2 compliant infrastructure

```bash
pip install humanbound
hb login
```

## On-Premises

Deploy Humanbound within your own infrastructure for full data sovereignty.

- **All data stays in your network**
- Azure Functions runtime (self-hosted)
- PostgreSQL (Cosmos DB compatible) database
- Requires your own LLM provider credentials

```bash
# Point CLI at your on-prem instance
hb --base-url https://my-humanbound-server.internal/api login
```

Contact [support@humanbound.ai](mailto:support@humanbound.ai) for on-prem deployment packages.

## Private Cloud

Dedicated Humanbound instance in your cloud tenant.

- **Isolated infrastructure** within your Azure/AWS subscription
- Managed by Humanbound team
- Custom domain and branding
- Same feature set as SaaS

## Feature Comparison

| Feature | SaaS | On-Prem | Private Cloud |
|---|---|---|---|
| Managed infrastructure | Yes | No | Yes |
| Data sovereignty | EU region | Your network | Your tenant |
| Automatic updates | Yes | Manual | Yes |
| Custom domain | No | Yes | Yes |
| SIEM integration | Yes | Yes | Yes |
| CLI support | Yes | Yes | Yes |
