"""Interactive MFFI browser adapter retained for legacy compatibility."""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from flavor_data_crawler.identifiers import normalize_cas, require_valid_cas
from flavor_data_crawler.models import LookupResult

MFFI_BASE_URL = "https://mffi.sjtu.edu.cn/database/search"
CAS_IN_TEXT = re.compile(r"\b\d{2,7}-\d{2}-\d\b")


def create_chrome_driver(*, headless: bool = False) -> webdriver.Chrome:
    """Create Chrome through Selenium Manager without disabling its sandbox."""

    options = webdriver.ChromeOptions()
    options.add_argument("--log-level=3")
    options.add_argument("--disable-notifications")
    if headless:
        options.add_argument("--headless=new")
    else:
        options.add_argument("--start-maximized")
    return webdriver.Chrome(options=options)


class MffiClient:
    """Look up sensory fields from the SJTU MFFI web interface."""

    def __init__(
        self,
        driver: webdriver.Chrome | None = None,
        *,
        timeout: float = 15,
        headless: bool = False,
    ) -> None:
        self.driver = driver or create_chrome_driver(headless=headless)
        self._owns_driver = driver is None
        self.timeout = timeout

    def close(self) -> None:
        if self._owns_driver:
            self.driver.quit()

    def __enter__(self) -> MffiClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def lookup_cas(self, cas: object) -> LookupResult:
        try:
            normalized = require_valid_cas(cas)
        except ValueError as exc:
            return LookupResult.failure("MFFI", status="invalid_input", message=str(exc))

        url = f"{MFFI_BASE_URL}?value={quote_plus(normalized)}&keyword=all"
        try:
            self.driver.get(url)
            rows = WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "tbody tr"))
            )
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < 7:
                    continue
                row_identifiers = {
                    normalize_cas(match) for match in CAS_IN_TEXT.findall(cells[3].text)
                }
                if normalized not in row_identifiers:
                    continue
                return LookupResult(
                    provider="MFFI",
                    source_url=url,
                    values={
                        "Chinese Name": cells[0].text.strip() or "\\",
                        "English Name": cells[1].text.strip() or "\\",
                        "Sensory Characteristics": cells[5].text.strip() or "\\",
                        "In Water": cells[6].text.strip() or "\\",
                    },
                )
            return LookupResult.failure(
                "MFFI",
                status="not_found",
                message=f"No exact CAS match for {normalized}",
                source_url=url,
            )
        except TimeoutException as exc:
            return LookupResult.failure(
                "MFFI",
                status="parse_error",
                message=f"Timed out waiting for result rows: {exc}",
                source_url=url,
            )
        except WebDriverException as exc:
            return LookupResult.failure(
                "MFFI",
                status="network_error",
                message=str(exc),
                source_url=url,
            )
