// Run with Playwright on NODE_PATH. All HTTP requests are mocked; no real database is used.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const artifactDir = path.join(root, 'backups', 'employee-list-ui-verification');
const template = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8')
    .replace(/\{\{ url_for\('static', filename='([^']+)'\) \}\}/g, (_, file) => '/static/' + file);

async function main() {
    fs.mkdirSync(artifactDir, { recursive: true });
    const browser = await chromium.launch({
        headless: true,
        executablePath: process.env.GZD_BROWSER_EXECUTABLE ||
            (process.platform === 'win32' ? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' : undefined),
    });
    try {
        const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('dialog', dialog => dialog.accept());
        let listError = false, saveError = false, holdSave = null;
        let records = Array.from({ length: 21 }, (_, index) => ({
            real_name: '测试员工' + String(index + 1).padStart(2, '0'),
            id_number: '110101199001011234', bank_account: '0012345678901234567',
            bank_address: '测试银行城市支行', phone: '1380000' + String(index).padStart(4, '0'), sx: 'csyg',
        }));
        records[0].real_name = "欧阳'测试<员工>";
        records[0].bank_address = '<img src=x onerror=window.injected=true>';
        let lastSaved = null, posts = 0;
        await page.route('**/*', async route => {
            const request = route.request();
            const url = new URL(request.url());
            const json = async (data, status = 200) => route.fulfill({ status, json: data });
            if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: template });
            if (url.pathname.startsWith('/static/')) return route.fulfill({
                contentType: 'text/css', body: fs.readFileSync(path.join(root, url.pathname), 'utf8'),
            });
            if (url.pathname === '/api/check-login') return json({ logged_in: true, username: '界面测试', is_admin: false });
            if (url.pathname === '/api/employees') {
                const q = url.searchParams.get('q') || '';
                if (q === 'slow') await new Promise(resolve => setTimeout(resolve, 250));
                if (listError) return json({ success: false, message: '模拟列表失败' }, 500);
                const data = records.filter(record => !q || [record.real_name, record.phone, record.sx].some(value => value.includes(q)));
                const current = Number(url.searchParams.get('page') || 1);
                const size = Number(url.searchParams.get('page_size') || 20);
                return json({ success: true, data: data.slice((current - 1) * size, current * size),
                    total: data.length, page: current, pages: Math.max(1, Math.ceil(data.length / size)), page_size: size });
            }
            if (url.pathname === '/api/employee' && request.method() === 'POST') {
                posts++;
                lastSaved = request.postDataJSON();
                if (holdSave) await holdSave;
                if (saveError) return json({ success: false, message: '模拟保存失败，请重试' }, 400);
                const existing = records.find(record => record.real_name === lastSaved.real_name);
                if (existing) Object.assign(existing, lastSaved);
                else records.push({ ...lastSaved, sx: '' });
                return json({ success: true, message: '资料保存成功' });
            }
            if (url.pathname.startsWith('/api/employee/') && request.method() === 'DELETE') {
                const name = decodeURIComponent(url.pathname.slice('/api/employee/'.length));
                records = records.filter(record => record.real_name !== name);
                return json({ success: true, message: '删除成功，可在回收站恢复' });
            }
            return json({ success: true });
        });
        await page.goto('http://employee-preview.test/');
        await page.locator('.tab[data-panel="entry"]').click();
        await page.waitForFunction(() => document.getElementById('employeeCount').textContent === '共 21 位员工');
        assert.equal(await page.locator('.employee-table tbody tr').count(), 20);
        assert.equal(await page.locator('.employee-table tbody img').count(), 0);
        assert.equal(await page.locator('.employee-table tbody th').first().textContent(), records[0].real_name);
        const text = await page.locator('.employee-table').textContent();
        assert(!text.includes(records[0].id_number));
        assert(!text.includes(records[0].bank_account));
        await page.screenshot({ path: path.join(artifactDir, 'desktop.png') });
        for (const width of [320, 375, 414, 768]) {
            await page.setViewportSize({ width, height: 900 });
            const bounds = await page.locator('#entry').evaluate(element => {
                const rect = element.getBoundingClientRect();
                return { left: rect.left, right: rect.right, width: innerWidth };
            });
            assert(bounds.left >= 0 && bounds.right <= bounds.width, 'Entry overflow at ' + width);
            assert(await page.locator('.employee-table tbody tr').first().evaluate(element => element.scrollWidth <= element.clientWidth), 'Row overflow at ' + width);
            await page.screenshot({ path: path.join(artifactDir, 'mobile-' + width + '.png') });
        }
        await page.setViewportSize({ width: 1280, height: 900 });
        await page.locator('.employee-row-actions button').first().click();
        await page.waitForFunction(() => document.getElementById('employeeDrawer').open);
        assert.equal(await page.locator('#realName').inputValue(), records[0].real_name);
        assert.equal(await page.locator('#idNumber').inputValue(), records[0].id_number);
        assert.equal(await page.locator('#bankAccount').inputValue(), records[0].bank_account);
        assert(await page.locator('#realName').evaluate(element => element.readOnly));
        await page.waitForFunction(() => getComputedStyle(document.getElementById('employeeDrawer')).opacity === '1');
        await page.screenshot({ path: path.join(artifactDir, 'drawer-desktop.png') });
        for (const width of [320, 375, 414, 768]) {
            await page.setViewportSize({ width, height: 900 });
            assert(await page.locator('#employeeDrawer').evaluate(element => element.scrollWidth <= element.clientWidth), 'Drawer overflow at ' + width);
            await page.screenshot({ path: path.join(artifactDir, 'drawer-' + width + '.png') });
        }
        await page.locator('#phone').fill('13900000000');
        saveError = true;
        await page.locator('#employeeSaveButton').click();
        await page.waitForFunction(() => document.getElementById('entryMessage').textContent.includes('模拟保存失败'));
        assert(await page.locator('#employeeDrawer').evaluate(element => element.open));
        assert.equal(await page.locator('#phone').inputValue(), '13900000000');
        saveError = false;
        let releaseSave;
        holdSave = new Promise(resolve => { releaseSave = resolve; });
        const beforePosts = posts;
        await page.locator('#employeeSaveButton').click();
        await page.waitForFunction(() => document.getElementById('employeeSaveButton').disabled);
        await page.evaluate(() => saveEmployee());
        assert.equal(posts, beforePosts + 1);
        releaseSave(); holdSave = null;
        await page.waitForFunction(() => !document.getElementById('employeeDrawer').open && !document.getElementById('employeeSaveButton').disabled);
        assert.equal(lastSaved.real_name, "欧阳'测试<员工>");
        assert.equal(lastSaved.bank_account, '0012345678901234567');
        await page.setViewportSize({ width: 1280, height: 900 });
        await page.locator('.employee-toolbar button').click();
        assert.equal(await page.locator('#realName').inputValue(), '');
        await page.locator('#employeeSaveButton').click();
        assert.equal(await page.locator('#realName').getAttribute('aria-invalid'), 'true');
        await page.locator('#realName').fill('测试新增员工');
        await page.locator('#phone').fill('13700000099');
        await page.locator('#employeeSaveButton').click();
        await page.waitForFunction(() => document.getElementById('employeeCount').textContent === '共 22 位员工');
        await page.locator('#employeeSearchInput').fill('13700000099');
        await page.locator('#employeeSearchForm button[type="submit"]').click();
        await page.waitForFunction(() => document.getElementById('employeeCount').textContent === '找到 1 位员工');
        assert.equal(await page.locator('.employee-table tbody th').textContent(), '测试新增员工');
        await page.locator('#employeeSearchInput').fill('不存在');
        await page.locator('#employeeSearchForm button[type="submit"]').click();
        await page.waitForFunction(() => document.getElementById('employeeCount').textContent === '找到 0 位员工');
        await page.getByRole('button', { name: '查看全部员工' }).click();
        await page.waitForFunction(() => document.getElementById('employeeCount').textContent === '共 22 位员工');
        // Ignore a slow, stale search response after a newer search finishes.
        await page.evaluate(async () => {
            employeeKeyword = 'slow';
            const old = loadEmployeeList(1);
            employeeKeyword = '13700000099';
            const latest = loadEmployeeList(1);
            await Promise.all([old, latest]);
        });
        assert.equal(await page.locator('#employeeCount').textContent(), '找到 1 位员工');
        await page.evaluate(() => resetEmployeeSearch());
        await page.waitForFunction(() => document.getElementById('employeeCount').textContent === '共 22 位员工');
        listError = true;
        await page.evaluate(() => loadEmployeeList());
        assert.equal(await page.locator('#employeeCount').textContent(), '加载失败');
        listError = false;
        await page.getByRole('button', { name: '重新加载' }).click();
        await page.waitForFunction(() => document.getElementById('employeeCount').textContent === '共 22 位员工');
        await page.locator('#employeePagination').getByRole('button', { name: '下一页' }).click();
        await page.waitForFunction(() => document.querySelectorAll('.employee-table tbody tr').length === 2);
        for (let i = 0; i < 2; i++) {
            await page.locator('.employee-more-button').first().click();
            assert(await page.locator('#employeeMoreMenu').evaluate(element => element.matches(':popover-open')));
            await page.locator('#employeeDeleteButton').click();
            await page.waitForFunction(count => document.getElementById('employeeCount').textContent === '共 ' + count + ' 位员工', 21 - i);
        }
        assert.equal(await page.locator('.employee-table tbody tr').count(), 20);
        assert.equal(await page.locator('#employeePagination button').count(), 0);
        assert.deepEqual(errors, []);
        console.log('Employee UI passed: table, masking, escaped text, search/races, pagination, drawer, save/error/loading, create/delete, responsive 320/375/414/768/1280.');
    } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
