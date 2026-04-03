"""
Document builder for converting scraped content to PDF artifacts.
Generates one PDF per platform with structured headings and source attribution.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
except ImportError:
    raise ImportError("reportlab is required. Install it via: pip install reportlab")


def build_per_platform_pdfs(
    scraped_content: Dict[str, Tuple[str, Dict]],
    output_dir: str = None,
) -> Dict[str, Dict]:
    """
    Generate one PDF per platform from scraped content.
    
    Args:
        scraped_content: Dict mapping platform name to (content_text, metadata)
        output_dir: Directory to save PDFs. Defaults to backend/data/guidelines
    
    Returns:
        Dict mapping platform name to artifact metadata (path, filename, stats)
    """
    if output_dir is None:
        output_dir = str(Path(__file__).parent.parent / "data" / "guidelines")
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    results = {}
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    for platform, (content, metadata) in scraped_content.items():
        filename = f"{platform}_guidelines_{timestamp}.pdf"
        output_path = os.path.join(output_dir, filename)
        
        try:
            _generate_pdf(
                platform=platform,
                content=content,
                metadata=metadata,
                output_path=output_path,
            )
            
            results[platform] = {
                "filename": filename,
                "filepath": output_path,
                "platform": platform,
                "scraped_count": metadata.get("scraped_count", 0),
                "failed_urls": metadata.get("failed_urls", []),
                "total_chars": metadata.get("total_chars", 0),
            }
            print(f"✅ Generated: {filename}")
        except Exception as e:
            print(f"❌ PDF generation failed for {platform}: {str(e)}")
            results[platform] = {
                "error": str(e),
                "platform": platform,
            }
    
    return results


def _generate_pdf(
    platform: str,
    content: str,
    metadata: Dict,
    output_path: str,
) -> None:
    """
    Generate a single PDF document for a platform.
    
    Args:
        platform: Platform name for use in title
        content: Combined scraped content text
        metadata: Scraping metadata including URL counts
        output_path: Destination filepath for PDF
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=18,
        textColor="#1f2937",
        spaceAfter=12,
        alignment=TA_CENTER,
    )
    
    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        fontSize=12,
        textColor="#374151",
        spaceAfter=6,
        spaceBefore=12,
    )
    
    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles["BodyText"],
        fontSize=10,
        textColor="#4b5563",
        spaceAfter=6,
        alignment=TA_LEFT,
    )
    
    # Build story
    story = []
    
    # Title
    title = f"{platform.upper()} Compliance Guidelines"
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 0.2 * inch))
    
    # Metadata summary
    summary_text = (
        f"<b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}<br/>"
        f"<b>Platform:</b> {platform}<br/>"
        f"<b>Sources Scraped:</b> {metadata.get('scraped_count', 0)}/{metadata.get('source_count', 0)}<br/>"
    )
    if metadata.get("failed_urls"):
        summary_text += f"<b>Failed URLs:</b> {len(metadata.get('failed_urls', []))}<br/>"
    
    story.append(Paragraph(summary_text, body_style))
    story.append(Spacer(1, 0.3 * inch))
    
    # Content sections
    # Split by "---" markers which denote URL boundaries
    sections = content.split("---")
    
    for i, section in enumerate(sections):
        section = section.strip()
        if not section:
            continue
        
        lines = section.split("\n", 1)
        if len(lines) == 2:
            url_or_header = lines[0].strip()
            body = lines[1].strip()
        else:
            url_or_header = "Content"
            body = section
        
        # Add section heading
        if url_or_header and url_or_header != "Content":
            story.append(Paragraph(url_or_header, heading_style))
        
        # Add body content - escape for reportlab
        escaped_body = body.replace("<", "&lt;").replace(">", "&gt;")
        for para_text in escaped_body.split("\n\n"):
            if para_text.strip():
                story.append(Paragraph(para_text.strip(), body_style))
        
        # Add spacing between sections
        story.append(Spacer(1, 0.15 * inch))
        
        # Add page break every N sections to prevent huge pages
        if (i + 1) % 10 == 0:
            story.append(PageBreak())
    
    # Build PDF
    doc.build(story)
