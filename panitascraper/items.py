import scrapy


class ScrapedPageItem(scrapy.Item):
    url = scrapy.Field()
    body = scrapy.Field()
    file_type = scrapy.Field()
    spider_name = scrapy.Field()
    run_id = scrapy.Field()
    records = scrapy.Field()
    checksum = scrapy.Field()
    is_new = scrapy.Field()
    storage_path = scrapy.Field()
