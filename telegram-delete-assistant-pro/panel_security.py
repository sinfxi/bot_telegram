"""Shared security middleware for the FXI Control web application."""
from fastapi.responses import JSONResponse


def install_admin_security(app, origin_allowed):
    """Install CSRF checks and baseline browser security headers on the real app."""

    @app.middleware("http")
    async def security_headers_and_admin_origin_guard(request, call_next):
        path = request.url.path
        unsafe_method = request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        protected_path = (
            path == "/admin"
            or path.startswith("/admin/")
            or path == "/owner"
            or path.startswith("/owner/")
            or path.startswith("/auth/")
        )

        if unsafe_method and protected_path:
            origin = request.headers.get("origin")
            fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
            if origin and not origin_allowed(request):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "درخواست بین‌مبدأیی مجاز نیست."},
                )
            if not origin and fetch_site == "cross-site":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "درخواست بین‌سایتی مسدود شد."},
                )

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'",
        )

        if (
            path in {"/admin", "/owner", "/login"}
            or path.startswith(("/admin/", "/owner/", "/auth/"))
        ):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"

        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        if request.url.scheme == "https" or forwarded_proto == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    return app
