from flavor_data_crawler.sources.chemicalbook import ChemicalBookLegacyClient
from flavor_data_crawler.sources.mffi import MffiClient


class FakeDriver:
    def __init__(self):
        self.visited = []
        self.quit_called = False

    def get(self, url):
        self.visited.append(url)

    def quit(self):
        self.quit_called = True


def test_chemicalbook_is_blocked_without_permission():
    result = ChemicalBookLegacyClient().lookup_cas("100-52-7")
    assert result.status == "blocked"
    assert "robots.txt" in result.message


def test_mffi_rejects_invalid_cas_before_browser_use():
    driver = FakeDriver()
    result = MffiClient(driver=driver).lookup_cas("100-52-8")
    assert result.status == "invalid_input"
    assert driver.visited == []
