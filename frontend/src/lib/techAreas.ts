/** The areas a coding prompt needs, in display order — same keys as TECH_AREAS in ai/text/dev_story_generator.py. */
export const TECH_AREAS: { key: string; label: string; example: string }[] = [
  { key: 'frontend', label: 'Frontend', example: 'e.g. Next.js 15 + TypeScript, Tailwind' },
  { key: 'backend', label: 'Backend', example: 'e.g. Python 3.12 + FastAPI' },
  { key: 'database', label: 'Database and storage', example: 'e.g. PostgreSQL 16, S3 for files' },
  { key: 'infrastructure', label: 'Hosting and infrastructure', example: 'e.g. AWS ECS Fargate, Terraform' },
  { key: 'authentication', label: 'Authentication and access', example: 'e.g. Azure AD (OIDC), role-based access' },
  { key: 'integrations', label: 'Integrations and messaging', example: 'e.g. REST to the CRM, SQS for events' },
  { key: 'testing', label: 'Testing', example: 'e.g. pytest, Playwright for end-to-end' },
  { key: 'ci_cd', label: 'CI/CD and delivery', example: 'e.g. GitHub Actions, trunk-based' },
  { key: 'conventions', label: 'Coding conventions and standards', example: 'e.g. clean architecture, OpenAPI first' },
]

export const TECH_AREA_LABEL: Record<string, string> = Object.fromEntries(TECH_AREAS.map((a) => [a.key, a.label]))
