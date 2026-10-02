## General Idea

From a paper invoice to a management decision, on one platform.

Invoice processes: most go through automatically, and people handle only the exceptions.
Approved invoices are purchase cost; sales orders are revenue. Because both land in the same data, an agent can explain why margin moved and trace it back to a specific supplier's invoices.

The audience takes part directly: they scan invoices with their phones and ask the data questions while you explain the code.

**The connecting question**: "Why did gross margin on the 500Wh battery pack drop in Q3?"

**_The answer_**: Revenue held steady, but Vendor B has invoiced 12% above the contract price since end of the summer. 


## Architecture

--->>>> Check Drawio pic


## Azure Services

Intake	Azure Logic Apps, Event Grid, Blob Storage	Pick up invoices from email or SharePoint, and uploads from the web app
Extraction	Azure Content Understanding	Classify, split and extract fields, with a confidence score and source location for each
Orchestration	Foundry workflows	Coordinate the agents in the invoice process
Approval	Foundry human-in-the-loop step (preview)	Pause the workflow for a person; approvals show in Teams and on the presenter screen
Contracts	Azure AI Search	Search contract PDFs for agreed prices and terms
Posting tools	Azure Functions (OpenAPI or MCP tools)	Look up POs and goods receipts; write approved invoices
Operational data	Azure SQL Database	Stands in for the ERP
Data platform	Fabric mirroring into OneLake	Replicates Azure SQL tables automatically, with no ETL to build
Business logic	Power BI semantic model	Holds the measures
Business vocabulary	Fabric IQ ontology and Fabric data agent	Lets the agent use business terms instead of table names
Analytics agent	Foundry prompt agent	Uses the Fabric IQ tool, Code Interpreter, and background mode
Audience front end	Azure Static Web Apps	Mobile page and presenter screen
Audience API	Azure Functions	Calls Azure services through a managed identity
Live updates	Azure Web PubSub (or polling)	Pushes scan status to phones and the presenter screen
Protection	Azure Front Door with web application firewall, Foundry guardrails	Rate limiting, prompt-injection protection
Distribution	Microsoft 365 Copilot and Teams	Where the agent is published
Security and monitoring	Entra ID managed identities, Key Vault, Application Insights	Identity, secrets, tracing

## System