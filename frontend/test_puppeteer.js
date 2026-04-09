import puppeteer from 'puppeteer';

(async () => {
    const browser = await puppeteer.launch();
    const page = await browser.newPage();

    page.on('console', msg => {
        if (msg.type() === 'error' || msg.type() === 'warning') {
            console.log(`PAGE MSG: ${msg.text()}`);
        }
    });

    page.on('pageerror', err => {
        console.log(`PAGE ERROR: ${err.message}`);
    });

    try {
        await page.goto('http://127.0.0.1:5173', { timeout: 10000 });
        await new Promise(r => setTimeout(r, 4000));
        // test the click on OITrendingView tab in sidebar
        const views = await page.$$('.sidebar-nav button');
        for (const v of views) {
            const text = await page.evaluate(el => el.textContent, v);
            if (text.includes("OI Trending")) {
                await v.click();
            }
        }
        await new Promise(r => setTimeout(r, 4000));
    } catch (err) {
        console.log("Could not load page:", err.message);
    }
    await browser.close();
})();
