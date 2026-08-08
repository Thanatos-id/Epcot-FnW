from epcot_fw.sources.allears import AllEarsAdapter
from epcot_fw.sources.base import SourceAdapter
from epcot_fw.sources.disney_food_blog import DisneyFoodBlogAdapter
from epcot_fw.sources.disney_official import DisneyOfficialAdapter
from epcot_fw.sources.disney_parks_blog import DisneyParksBlogAdapter
from epcot_fw.sources.touring_plans import TouringPlansAdapter
from epcot_fw.sources.wdw_prep_school import WdwPrepSchoolAdapter
from epcot_fw.sources.wdwmagic import WdwMagicAdapter

SOURCE_REGISTRY: dict[str, SourceAdapter] = {
    adapter.key: adapter
    for adapter in (
        DisneyOfficialAdapter(),
        DisneyParksBlogAdapter(),
        TouringPlansAdapter(),
        AllEarsAdapter(),
        WdwMagicAdapter(),
        DisneyFoodBlogAdapter(),
        WdwPrepSchoolAdapter(),
    )
}
