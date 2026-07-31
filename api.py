class DobNowAPI:

    PUBLIC_BASE = "https://a810-dobnow.nyc.gov/Publish/WrapperPP/PublicPortal.svc"

    SERVICE_BASE = "https://a810-dobnow.nyc.gov/Publish/WrapperServicePP/WrapperService.svc"

    def __init__(self, session):
        self.session = session

    def post(self, base, endpoint, body):

        return self.session.browser_fetch(
            f"{base}/{endpoint}",
            body
        )

    def get(self, base, endpoint):

        return self.session.browser_get(
            f"{base}/{endpoint}"
        )

    def build_display(self, bin_number, street):

        return self.post(
            self.PUBLIC_BASE,
            "getPublicPortalBuildDisplay",
            {
                "BIN": str(bin_number),
                "SearchBy": "2",
                "StreetName": street
            }
        )

    def partial_job(self, guid):

        return self.post(
            self.SERVICE_BASE,
            "GetPartialJobFilingService",
            {
                "RelatedEntityLogicalName": "dobnyc_delegates",
                "JobFilingGUID": guid
            }
        )

    def get_job_filing_pw1(self, guid):

        return self.get(
            self.SERVICE_BASE,
            f"GetJobFilingPW1/{guid}"
        )

    def get_scope_of_work_st(self, guid):

        return self.get(
            self.SERVICE_BASE,
            f"GetScopeOfWorkST/{guid}"
        )

    def get_pw1_configuration(self, work_type, job_type):

        return self.post(
            self.SERVICE_BASE,
            "GetPW1Configuration",
            {
                "WorkType": [
                    {
                        "WorkTypeName": work_type,
                        "JobType": job_type
                    }
                ],
                "JobType": job_type
            }
        )
        
    def get_public_portal_partial_job_filing(
        self,
        guid,
        filing_includes,
        current_status,
        is_plan_approved
    ):

        return self.post(
            self.PUBLIC_BASE,
            "GetPublicPortalPartialJobFiling",
            {
                "Applicant": None,
                "RelatedEntityLogicalName": "dobnyc_documentlist",
                "JobFilingGUID": guid,
                "FilingIncludes": filing_includes,
                "CurrentFilingStatusValue": current_status,
                "IsPlanApproved": is_plan_approved
            }
        )
        
    def partial_job_zd1wd(self, guid):

        return self.post(
            self.SERVICE_BASE,
            "GetPartialJobFilingServiceZD1WD",
            {
                "RelatedEntityLogicalName": "dobnyc_documentlist",
                "JobFilingGUID": guid
            }
        )

    def download_from_documentum(self, uploaded_path, download_path):

        return self.post(
            self.SERVICE_BASE,
            "downloadFromDocumentum",
            {
                "uploadedPath": uploaded_path,
                "downloadPath": download_path
            }
        )