// Browser regression: original XLS uploads at both stages; output is explicitly XLSX.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const template = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8')
    .replace(/\{\{ url_for\('static', filename='([^']+)'\) \}\}/g, (_, file) => '/static/' + file);

async function main() {
    const browser = await chromium.launch({ headless: true,
        executablePath: process.env.GZD_BROWSER_EXECUTABLE ||
            (process.platform === 'win32' ? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' : undefined) });
    try {
        const page = await browser.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        let previewFailed = false;
        let previewBody = null, confirmBody = null;
        let previewCount = 0, confirmCount = 0;
        let holdPreview = false, releasePreview = null;
        let confirmFailed = false;
        const sourceBytes = Buffer.from('original-XLS-test-bytes');
        await page.route('**/*', async route => {
            const request = route.request();
            const url = new URL(request.url());
            if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: template });
            if (url.pathname.startsWith('/static/')) return route.fulfill({ contentType: 'text/css',
                body: fs.readFileSync(path.join(root, url.pathname), 'utf8') });
            if (url.pathname === '/api/check-login') return route.fulfill({ json: { logged_in: true, username: '测试' } });
            if (url.pathname === '/api/smart-fill-preview') {
                previewBody = request.postDataBuffer();
                previewCount++;
                if (holdPreview) await new Promise(resolve => { releasePreview = resolve; });
                if (previewFailed) return route.fulfill({ status: 422, json: {
                    success: false, message: 'Excel 转换不可用，请另存为 .xlsx', fallback_available: true } });
                const body = request.postDataBuffer().toString();
                const provided = body.includes('name="names"');
                const overwrite = /name="overwrite"\r\n\r\n1\r\n/.test(body);
                return route.fulfill({ json: { success: true, preview_token: 'verified-token',
                    name_mode: provided ? 'provided' : 'template', requested_names: provided ? 1 : 0, overwrite,
                    preview: { confidence: 1, source_format: 'xls', output_format: 'xlsx', converted: true,
                        tables: [{ sheet: '工资表', header_row: 2, data_start_row: 3,
                            fields: [{ label: '姓名', column: 'A', header: '姓名', header_row: 2 }] }] } } });
            }
            if (url.pathname === '/api/smart-fill-confirm') {
                confirmBody = request.postDataBuffer();
                confirmCount++;
                if (confirmFailed) return route.fulfill({ status: 422, json: {
                    success: false, message: '模拟填写失败，原文件未改动' } });
                return route.fulfill({ headers: {
                    'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    'Content-Disposition': 'attachment; filename="payroll_filled.xlsx"',
                    'X-Smart-Fill-Matched': '1', 'X-Smart-Fill-Cells': '3',
                }, body: Buffer.from('xlsx-result') });
            }
            return route.fulfill({ json: { success: true, data: [], total: 0, page: 1, pages: 1, page_size: 20 } });
        });
        await page.goto('http://smart-fill-preview.test/');
        await page.locator('.tab[data-panel="export"]').click();
        assert.equal(await page.locator('#smartFillFile').getAttribute('accept'), '.xls,.xlsx');
        const useNames = page.getByRole('switch', { name: '使用姓名名单', exact: true });
        const overwrite = page.getByRole('switch', { name: '清空原有人员', exact: true });
        for (const control of [useNames, overwrite]) {
            assert.equal(await control.getAttribute('aria-checked'), 'false');
            assert.equal((await control.textContent()).trim(), '关闭');
            assert.equal(await control.evaluate(el => el.tagName), 'BUTTON');
        }
        await page.locator('#smartFillFile').setInputFiles({ name: '工资表.XLS',
            mimeType: 'application/vnd.ms-excel', buffer: sourceBytes });
        assert.equal(await page.locator('#smartFillFileName').textContent(), '工资表.XLS');
        assert.equal(await page.locator('#smartFillUploadArea .upload-excel-icon').textContent(), 'XLS');
        // Defaults: template names and fill blanks, no supplied roster or clearing.
        await page.locator('#smartFillBtn').click();
        await page.locator('#smartFillPreview').waitFor({ state: 'visible' });
        assert(!previewBody.toString().includes('name="names"'));
        assert(/name="overwrite"\r\n\r\n0\r\n/.test(previewBody.toString()));
        assert((await page.locator('#smartFillPreviewMeta').textContent()).includes('读取模板姓名列'));
        await useNames.focus();
        await page.keyboard.press('Space');
        assert.equal(await useNames.getAttribute('aria-checked'), 'true');
        assert(await page.locator('#smartFillPreview').isHidden());
        await page.evaluate(() => confirmSmartFill());
        assert.equal(confirmCount, 0);
        const callsBeforeValidation = previewCount;
        await page.locator('#smartFillBtn').click();
        assert.equal(previewCount, callsBeforeValidation);
        assert.equal(await useNames.getAttribute('aria-invalid'), 'true');
        assert((await page.locator('#smartFillModeSummary').textContent()).includes('先添加人员'));
        // Enter activates the same native button; keep the user's selection on return.
        await useNames.focus();
        await page.keyboard.press('Enter');
        assert.equal(await useNames.getAttribute('aria-checked'), 'false');
        await overwrite.click();
        assert.equal(await useNames.getAttribute('aria-checked'), 'true');
        assert(await useNames.isDisabled());
        assert((await page.locator('#smartFillUseNamesHelp').textContent()).includes('必须'));
        await overwrite.click();
        assert.equal(await useNames.getAttribute('aria-checked'), 'false');
        assert(await useNames.isEnabled());
        await useNames.click();
        await overwrite.click();
        await overwrite.click();
        assert.equal(await useNames.getAttribute('aria-checked'), 'true');
        await overwrite.click();
        await page.locator('#manualNameInput').fill('张三');
        await page.locator('#manualNameInput').press('Enter');
        await page.locator('#smartFillBtn').click();
        await page.locator('#smartFillPreview').waitFor({ state: 'visible' });
        assert((await page.locator('#smartFillPreviewMeta').textContent()).includes('XLS 模板转换为 XLSX'));
        assert(previewBody.includes(sourceBytes));
        assert(previewBody.toString().includes('application/vnd.ms-excel'));
        const downloaded = page.waitForEvent('download');
        await page.locator('#smartFillConfirmBtn').click();
        assert.equal((await downloaded).suggestedFilename(), 'payroll_filled.xlsx');
        assert(confirmBody.includes(sourceBytes));
        assert(confirmBody.toString().includes('verified-token'));
        await page.locator('#smartFillPreview').waitFor({ state: 'hidden' });
        // Confirm failure must unlock modes and retain the valid preview for retry.
        await page.locator('#smartFillBtn').click();
        await page.locator('#smartFillPreview').waitFor({ state: 'visible' });
        confirmFailed = true;
        await page.locator('#smartFillConfirmBtn').click();
        await page.waitForFunction(() => document.getElementById('smartFillMessage').textContent.includes('模拟填写失败'));
        assert(await overwrite.isEnabled());
        assert(await page.locator('#smartFillPreview').isVisible());
        confirmFailed = false;
        await overwrite.click();
        // A changed file during recognition must not resurrect its stale mapping.
        holdPreview = true;
        await page.locator('#smartFillBtn').click();
        await page.waitForFunction(() => document.getElementById('smartFillOptions').dataset.state === 'loading');
        assert(await useNames.isDisabled());
        assert(await overwrite.isDisabled());
        await page.locator('#smartFillFile').setInputFiles({ name: '替换工资表.xls',
            mimeType: 'application/vnd.ms-excel', buffer: Buffer.from('changed-XLS') });
        await page.waitForFunction(() => !document.getElementById('smartFillPreview').style.display.includes('block'));
        assert(releasePreview);
        releasePreview();
        holdPreview = false;
        await page.waitForFunction(() => !document.getElementById('smartFillBtn').disabled);
        assert(await page.locator('#smartFillPreview').isHidden());
        assert.equal(await page.evaluate(() => smartFillPreviewToken), null);
        // Engine failure must keep the chosen file and the existing manual export.
        previewFailed = true;
        await page.locator('#smartFillBtn').click();
        await page.waitForFunction(() => document.getElementById('smartFillMessage').textContent.includes('转换不可用'));
        assert.equal(await page.locator('#smartFillFile').evaluate(input => input.files[0].name), '替换工资表.xls');
        assert(await page.getByRole('button', { name: '导出', exact: true }).isEnabled());
        await page.locator('#smartFillFile').setInputFiles({ name: '新模板.xlsx',
            mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('xlsx') });
        assert.equal(await page.locator('#smartFillUploadArea .upload-excel-icon').textContent(), 'XLSX');
        await useNames.click();
        assert.equal(await useNames.getAttribute('aria-checked'), 'false');
        assert.equal(await overwrite.getAttribute('aria-checked'), 'false');
        // Component layout, touch target and reduced motion at all required widths.
        const screenshots = path.join(root, 'backups', 'smart-fill-switches-ui-verification');
        fs.mkdirSync(screenshots, { recursive: true });
        for (const width of [320, 375, 414, 768, 1280]) {
            await page.setViewportSize({ width, height: 1000 });
            const bounds = await page.locator('#smartFillOptions').boundingBox();
            assert(bounds.x >= 0 && bounds.x + bounds.width <= width);
            assert(await page.locator('#smartFillOptions').evaluate(el => el.scrollWidth <= el.clientWidth));
            for (const control of [useNames, overwrite]) {
                const rect = await control.boundingBox();
                assert(rect.height >= 44 && rect.width >= 44);
            }
            await page.locator('#smartFillOptions').screenshot({ path: path.join(screenshots, 'options-' + width + '.png') });
        }
        await page.emulateMedia({ reducedMotion: 'reduce' });
        assert.equal(await page.locator('#smartFillUseNames .smart-fill-switch-track').evaluate(
            el => getComputedStyle(el, '::after').transitionDuration), '0s');
        assert.deepEqual(errors, []);
        console.log('Smart-fill browser checks passed: switches/defaults/keyboard/dependencies, mapping invalidation, loading/error recovery, stale responses, XLS flow, 5 widths and reduced motion.');
    } finally {
        await browser.close();
    }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
