# Overview

Web2Print is a Flask-based web application for managing print services. Users can register, upload PDF files, and get automated cost estimates based on color analysis. The system analyzes PDFs to detect color vs monochrome pages and provides detailed pricing for different print configurations including paper types, binding options, and finishing services.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture
- **Template Engine**: Jinja2 templates with Flask
- **Styling**: Bootstrap 4.5.2 for responsive UI components
- **JavaScript**: Vanilla JavaScript for file upload handling and form interactions
- **Static Assets**: CSS organized in separate files with custom styling for print configuration forms

## Backend Architecture
- **Web Framework**: Flask with modular route handling
- **Database ORM**: SQLAlchemy for database operations
- **File Processing**: PyPDF2 and PyMuPDF (fitz) for PDF analysis and color detection
- **Session Management**: Flask sessions with configurable timeouts and security settings
- **File Upload**: Werkzeug secure filename handling

## Data Storage
- **Primary Database**: SQLite for user data, file metadata, and order configurations
- **User Model**: Comprehensive schema including personal info, file details, color analysis results, and print configuration options
- **File Storage**: Local file system for uploaded PDFs with secure filename generation

## Authentication & Authorization
- **User Authentication**: CPF-based login system
- **Session Security**: HTTP-only cookies with CSRF protection
- **User Registration**: Name, CPF, and address validation with CEP integration

## PDF Processing System
- **Color Analysis**: Automated detection of color vs monochrome pages using PyMuPDF
- **Page Counting**: Extraction of total page count from uploaded PDFs
- **Cost Estimation**: Dynamic pricing based on color analysis, paper type, binding options, and quantity

## Print Configuration Features
- **Print Types**: Color, monochrome, and mixed printing options
- **Paper Options**: Multiple paper types (sulfite, couche, recycled) with various weights
- **Binding Services**: Spiral, wire-o, hardcover, and stapling options
- **Finishing Options**: Lamination, varnish, folding services
- **Quantity Management**: Copy quantity with bulk pricing calculations

# External Dependencies

## Python Libraries
- **Flask**: Web framework for HTTP handling and routing
- **Flask-SQLAlchemy**: Database ORM for user and order management
- **PyPDF2**: PDF parsing and page extraction
- **PyMuPDF (fitz)**: Advanced PDF color analysis and content processing
- **Werkzeug**: Secure file upload handling
- **requests**: HTTP client for external API integrations (CEP validation)

## Frontend Libraries
- **Bootstrap 4.5.2**: CSS framework via CDN for responsive design
- **jQuery 3.5.1**: JavaScript library for DOM manipulation (via CDN)
- **Popper.js**: Tooltip and popover positioning (via CDN)

## External APIs
- **CEP Validation Service**: Integration for Brazilian postal code validation during user registration

## File System Dependencies
- **Upload Directory**: Local storage for PDF files with secure naming
- **Static Assets**: CSS, JavaScript, and image files served via Flask static routing

# Recent Changes & Updates

## September 26, 2025 - WooCommerce API Integration
- **New API Endpoints**: Implemented dedicated REST API endpoints for WooCommerce integration
  - `/api/v1/calculate_final`: Main endpoint for cost calculations with JSON request/response
  - `/api/v1/health`: Health check endpoint for API monitoring
- **Security Features**: Comprehensive input validation, CORS support, structured error handling
- **Integration Ready**: Full compatibility with WooCommerce REST API ecosystem and webhooks
- **Production Quality**: Robust error handling, logging, and structured JSON responses

## API Integration Features
- **Input Validation**: Complete validation of color_pages, mono_pages, paper types, weights, binding, and finishing options
- **CORS Support**: Cross-origin resource sharing configured for WooCommerce domains
- **Error Handling**: Structured error responses with specific error codes for debugging
- **Fallback Logic**: Intelligent defaults and closest-match algorithms for invalid inputs
- **Logging System**: Detailed request/response logging for integration monitoring and debugging

## WooCommerce Compatibility
- **JSON Request/Response**: Clean API interface following REST best practices
- **Flexible Parameters**: Support for optional parameters with intelligent defaults
- **Cost Breakdown**: Detailed cost structure including pages, binding, finishing, and total costs
- **Business Logic**: Direct integration with existing `calculate_advanced_cost` function using database-driven pricing

## September 26, 2025 - WordPress Plugin Integration
- **Complete Plugin**: Full WordPress plugin created for WooCommerce integration
  - `wordpress-plugin/web2print-integration.php`: Main plugin file with PHP logic
  - `wordpress-plugin/js/web2print-ajax.js`: JavaScript for AJAX and user interface
  - `wordpress-plugin/templates/calculator-form.php`: HTML template for PDF calculator
  - `wordpress-plugin/css/web2print-style.css`: Responsive CSS styling
- **Plugin Features**: PDF upload with drag & drop, real-time cost calculation, WooCommerce cart integration
- **WordPress Hooks**: Implemented `woocommerce_before_calculate_totals` and `woocommerce_add_to_cart` for seamless integration
- **Admin Interface**: Configuration page for API endpoint and authentication key management
- **Production Ready**: Complete plugin ready for installation and deployment in WordPress/WooCommerce stores

## September 26, 2025 - MAJOR ARCHITECTURAL OPTIMIZATION: Centralized PDF Analysis
- **New Flask API Route**: `/api/v1/analyze_pdf_url` endpoint for centralized PDF analysis via URL
  - **PyMuPDF Integration**: High-precision color detection using advanced PDF processing library
  - **Intelligent Fallback**: Automatic fallback to PyPDF2 if PyMuPDF unavailable, with method tracking
  - **Production Security**: Comprehensive SSRF protection, API key authentication, file validation
- **WordPress Integration Optimization**: Plugin modified to send PDF URLs to Flask instead of local analysis
  - **analyze_pdf_via_flask()**: New method for secure API communication with Flask backend
  - **Session Management**: Complete analysis data persistence in WooCommerce session for validation
  - **File Workflow**: Maintains permanent PDF storage for print shop access while leveraging Flask precision
- **Security Hardening**: Production-ready security implementations
  - **SSRF Protection**: IPv4/IPv6 validation, private IP blocking, redirect prevention
  - **API Authentication**: Mandatory API key with production environment validation
  - **Content Validation**: Strict Content-Type checking and file size limits (50MB)
  - **Resource Management**: Guaranteed temporary file cleanup and stream-based downloads
- **System Benefits**:
  - **Accuracy**: PyMuPDF provides superior color detection compared to regex-based analysis
  - **Centralization**: Single source of truth for PDF analysis logic in Flask backend
  - **Security**: Enterprise-grade security protections for production deployment
  - **Maintainability**: Centralized analysis logic reduces code duplication between systems

## September 26, 2025 - Enhanced PDF URL Metadata Management for Print Shop Access
- **Robust URL Validation**: Comprehensive validation of PDF URLs before saving to WooCommerce order metadata
  - **Accessibility Testing**: Real-time URL verification via wp_remote_head with timeout controls
  - **Status Tracking**: Detailed metadata including verification status, check timestamps, and validity flags
  - **Error Handling**: Graceful handling of invalid URLs with debugging information preserved
- **Comprehensive Metadata Storage**: Complete PDF file information saved as order item metadata
  - **Essential Data**: URL, filename, filesize, local path fallback, content hash, verification token
  - **Technical Metadata**: Analysis method, upload timestamp, verification status for debugging
  - **Print Shop Access**: Direct download links and formatted display for easy print shop workflow
- **Detailed Logging System**: Full audit trail of PDF URL handling throughout the order process
  - **Session to Cart**: Logs during data transfer from session to cart items
  - **Cart to Order**: Detailed logging during order creation with URL validation results
  - **Debugging Support**: Hash and token truncation for security while maintaining troubleshooting capability
- **Integration Hook**: WordPress action 'web2print_order_item_saved' for external system integration
  - **Data Payload**: Complete PDF metadata with order/item IDs for third-party systems
  - **Print Shop Integration**: Enables automatic notification of graphic shops when orders are placed
  - **ERP Connectivity**: Facilitates integration with external workflow and production management systems
- **Production Benefits**:
  - **Reliability**: Multiple fallback mechanisms ensure print shop always has access to PDF files
  - **Traceability**: Complete audit trail from upload through order completion
  - **Integration Ready**: Designed for seamless connection with external printing workflow systems
  - **Security Compliant**: Sensitive data protection while maintaining operational transparency

## September 26, 2025 - Robust PDF File Validation System
- **Multi-Layer Validation**: Comprehensive PDF file validation preventing invalid uploads before Flask processing
  - **Client-side JavaScript**: Extension (.pdf), MIME type (application/pdf), file size (1KB-50MB) validation
  - **Server-side WordPress**: Magic bytes check (%PDF), wp_check_filetype_and_ext, file integrity validation
  - **HTML Template**: Enhanced accept attribute (.pdf,application/pdf) for better browser filtering
- **Consistent Error Messaging**: Unified user experience with clear, specific error messages
  - **Standard Message**: "Formato inválido. Apenas PDFs são aceitos." for format errors
  - **Size Validation**: "Arquivo muito grande. Máximo 50MB." for oversized files
  - **Server Integration**: Error messages from WordPress server displayed in JavaScript UI
- **Enhanced Error Handling**: Improved AJAX error processing with server message parsing
  - **Response Parsing**: Intelligent parsing of server JSON responses for specific error messages
  - **Fallback Messaging**: Graceful fallback to localized error texts when parsing fails
  - **User Experience**: Clear feedback for all upload and validation scenarios
- **Security Features**: Multi-level protection against invalid file uploads
  - **Magic Bytes Verification**: Server-side check for PDF signature (%PDF) to prevent spoofed files
  - **File Integrity Check**: Basic file opening and reading validation to detect corruption
  - **Consistent Limits**: 50MB maximum size limit aligned between client and server validation
- **System Benefits**:
  - **User Experience**: Immediate feedback prevents unnecessary server requests for invalid files
  - **Performance**: Client-side validation reduces server load and improves response times
  - **Security**: Multiple validation layers prevent malicious or corrupted file uploads
  - **Reliability**: Consistent validation ensures only valid PDFs reach Flask analysis system