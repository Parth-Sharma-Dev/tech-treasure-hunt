import { test, expect } from '@playwright/test'

test('shows the hunt, five rounds and a connected status', async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }))
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Find the treasure.')
  await expect(page.getByRole('status')).toHaveText('Connected')
  await expect(page.getByRole('listitem')).toHaveCount(5)
  await expect(page.getByText('Team access opens soon')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  expect(overflow).toBe(false)
})

test('keeps event information readable when the service is unavailable', async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ status: 503, json: { status: 'unavailable' } }))
  await page.goto('/')
  await expect(page.getByRole('status')).toHaveText('Connection unavailable')
  await expect(page.getByRole('heading', { name: 'One team. Five challenges.' })).toBeVisible()
})
