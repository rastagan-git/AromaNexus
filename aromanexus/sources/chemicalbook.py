"""Permission-gated ChemicalBook browser compatibility adapter.

ChemicalBook currently disallows the routes used here in robots.txt. This module
therefore never runs unless a user explicitly confirms they have permission.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from aromanexus.identifiers import require_valid_cas
from aromanexus.models import LookupResult
from aromanexus.sources.mffi import create_chrome_driver

CHEMICALBOOK_SEARCH_URL = "https://www.chemicalbook.com/Search.aspx"
CHEMICALBOOK_ROBOTS_URL = "https://www.chemicalbook.com/robots.txt"
PERMISSION_PHRASE = "I HAVE PERMISSION"


class ManualVerificationRequired(RuntimeError):
    """Signal that the visible browser needs user inspection or CAPTCHA handling."""


class ChemicalBookLegacyClient:
    """Retain the original lookup as an explicit, interactive compatibility mode."""

    def __init__(
        self,
        driver: webdriver.Chrome | None = None,
        *,
        permission_confirmed: bool = False,
        timeout: float = 8,
    ) -> None:
        self.permission_confirmed = permission_confirmed
        self.driver = driver
        self._owns_driver = driver is None
        self.timeout = timeout

    def close(self) -> None:
        if self._owns_driver and self.driver is not None:
            self.driver.quit()

    def __enter__(self) -> ChemicalBookLegacyClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def lookup_cas(self, cas: object) -> LookupResult:
        if not self.permission_confirmed:
            return LookupResult.failure(
                "ChemicalBook",
                status="blocked",
                message=(
                    "Automated access is disabled because the current robots.txt disallows the "
                    "search and product-property routes. Run only with documented permission."
                ),
                source_url=CHEMICALBOOK_ROBOTS_URL,
            )
        try:
            normalized = require_valid_cas(cas)
        except ValueError as exc:
            return LookupResult.failure("ChemicalBook", status="invalid_input", message=str(exc))
        if self.driver is None:
            self.driver = create_chrome_driver(headless=False)

        url = f"{CHEMICALBOOK_SEARCH_URL}?keyword={quote_plus(normalized)}"
        try:
            self.driver.get(url)
            wait = WebDriverWait(self.driver, self.timeout)
            selector = "//a[text()='化学性质' or contains(@href, 'ProductChemicalProperties')]"
            try:
                wait.until(EC.element_to_be_clickable((By.XPATH, selector))).click()
            except TimeoutException as exc:
                raise ManualVerificationRequired(
                    "The property link was not available. Inspect the visible browser for a "
                    "CAPTCHA, access block, slow page, or a genuine no-result response."
                ) from exc

            windows = self.driver.window_handles
            self.driver.switch_to.window(windows[-1])
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "th")))
            detail_url = self.driver.current_url
            values = {
                "CB_Odor_Desc": self._text_or_sentinel(
                    "//th[contains(text(), '气味')]/following-sibling::td"
                ),
                "CB_Odor_Threshold": self._text_or_sentinel(
                    "//th[contains(text(), '嗅觉阈值')]/following-sibling::td"
                ),
                "CB_Odor_Type": self._text_or_sentinel(
                    "//th[contains(text(), '香型')]/following-sibling::td"
                ),
            }
            if len(windows) > 1:
                self.driver.close()
                self.driver.switch_to.window(windows[0])
            status = "ok" if any(value != "\\" for value in values.values()) else "not_found"
            return LookupResult(
                provider="ChemicalBook",
                values=values,
                source_url=detail_url if status == "ok" else url,
                status=status,
                message="" if status == "ok" else f"No odor fields found for {normalized}",
            )
        except ManualVerificationRequired:
            raise
        except (TimeoutException, WebDriverException) as exc:
            return LookupResult.failure(
                "ChemicalBook",
                status="network_error",
                message=str(exc),
                source_url=url,
            )

    def _text_or_sentinel(self, xpath: str) -> str:
        try:
            value = self.driver.find_element(By.XPATH, xpath).text.strip()
        except Exception:
            value = ""
        return value or "\\"
