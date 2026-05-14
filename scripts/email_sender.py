# -*- coding: utf-8 -*-
"""
21天龙头策略V3.3 - 邮件发送模块
支持Gmail发送报告到 fys2388@gmail.com
"""

import smtplib
import ssl
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from typing import Optional, Tuple
import json


class EmailSender:
    """邮件发送器"""
    
    def __init__(self, config_path: str = None):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.config_path = config_path or f"{self.base_dir}/config/email_config.json"
        
        self._load_config()
    
    def _load_config(self):
        """加载邮件配置"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.email_config = self.config.get("email_config", {})
        self.smtp_config = self.config.get("SMTP配置", {})
        self.subject_format = self.config.get("邮件主题格式", {})
    
    def get_recipient(self) -> str:
        """获取收件人"""
        return self.email_config.get("收件人", "fys2388@gmail.com")
    
    def generate_subject(self, report_type: str, **kwargs) -> str:
        """
        生成邮件主题
        
        report_type: 龙头股池 / 复盘报告 / 周度报告 / 月度报告
        """
        date = kwargs.get("date", datetime.now().strftime("%Y%m%d"))
        year = kwargs.get("year", datetime.now().year)
        month = kwargs.get("month", datetime.now().month)
        week = kwargs.get("week", datetime.now().isocalendar()[1])
        
        templates = {
            "龙头股池": self.subject_format.get("龙头股池", ""),
            "复盘报告": self.subject_format.get("复盘报告", ""),
            "周度报告": self.subject_format.get("周度报告", ""),
            "月度报告": self.subject_format.get("月度报告", "")
        }
        
        template = templates.get(report_type, "{date} {report_type}")
        subject = template.format(date=date, year=year, month=month, week=week)
        
        return subject
    
    def create_email(self, 
                    subject: str,
                    content: str,
                    report_type: str = "报告",
                    attachment_path: str = None) -> MIMEMultipart:
        """
        创建邮件
        
        subject: 邮件主题
        content: 邮件正文（Markdown格式）
        report_type: 报告类型
        attachment_path: 附件路径（可选）
        """
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.smtp_config.get("username", "noreply@gmail.com")
        msg['To'] = self.get_recipient()
        
        # HTML版本的正文（增强可读性）
        html_content = self._markdown_to_html(content)
        
        # 添加纯文本和HTML两个版本
        part1 = MIMEText(content, 'plain', 'utf-8')
        part2 = MIMEText(html_content, 'html', 'utf-8')
        
        msg.attach(part1)
        msg.attach(part2)
        
        # 添加附件（Markdown文件）
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
                encoders.encode_base64(part)
                
                # 附件文件名
                filename = os.path.basename(attachment_path)
                part.add_header('Content-Disposition', 'attachment', 
                              filename=('utf-8', '', filename))
                msg.attach(part)
        
        return msg
    
    def _markdown_to_html(self, md_content: str) -> str:
        """将Markdown转换为简单的HTML"""
        # 简化转换，仅处理基本格式
        html = md_content
        
        # 标题
        html = html.replace('## ', '<h2>').replace('\n', '</h2>\n', 1)
        html = html.replace('### ', '<h3>').replace('\n', '</h3>\n', 1)
        
        # 粗体
        html = html.replace('**', '<strong>', 1)
        html = html.replace('**', '</strong>', 1)
        
        # 换行
        html = html.replace('\n\n', '</p><p>')
        
        # 表格处理（简化）
        lines = html.split('\n')
        new_lines = []
        in_table = False
        
        for line in lines:
            if '|' in line and line.strip().startswith('|'):
                if not in_table:
                    new_lines.append('<table border="1" cellpadding="5" cellspacing="0">')
                    in_table = True
                
                if '---' in line:
                    continue  # 跳过分隔行
                
                cells = [c.strip() for c in line.split('|')[1:-1]]
                cell_tags = '<td>' + '</td><td>'.join(cells) + '</td>'
                new_lines.append(f'<tr>{cell_tags}</tr>')
            else:
                if in_table:
                    new_lines.append('</table>')
                    in_table = False
                new_lines.append(line)
        
        if in_table:
            new_lines.append('</table>')
        
        html = '\n'.join(new_lines)
        
        return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; line-height: 1.6; padding: 20px; }}
h1 {{ color: #333; border-bottom: 2px solid #1a73e8; padding-bottom: 10px; }}
h2 {{ color: #1a73e8; margin-top: 20px; }}
h3 {{ color: #555; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
th {{ background-color: #1a73e8; color: white; text-align: left; padding: 10px; }}
td {{ padding: 8px; border: 1px solid #ddd; }}
tr:nth-child(even) {{ background-color: #f9f9f9; }}
.warning {{ color: #d32f2f; font-weight: bold; }}
.success {{ color: #388e3c; font-weight: bold; }}
.disclaimer {{ color: #666; font-size: 12px; border-top: 1px solid #ddd; padding-top: 15px; margin-top: 30px; }}
</style>
</head>
<body>
{html}
<div class="disclaimer">
⚠️ 免责声明：本报告仅供参考和学习研究之用，不构成任何投资建议。
股市有风险，投资需谨慎。请您根据自身情况做出独立的投资决策。
</div>
</body>
</html>
"""
    
    def send_email(self, 
                  subject: str,
                  content: str,
                  report_type: str = "报告",
                  attachment_path: str = None) -> Tuple[bool, str]:
        """
        发送邮件
        
        返回：(是否成功, 消息)
        """
        try:
            # 创建邮件
            msg = self.create_email(subject, content, report_type, attachment_path)
            
            # 连接SMTP服务器
            host = self.smtp_config.get("host", "smtp.gmail.com")
            port = self.smtp_config.get("port", 587)
            username = self.smtp_config.get("username", "")
            password = self.smtp_config.get("password", "")
            
            if not username or not password:
                return False, "SMTP配置不完整，请先配置用户名和密码"
            
            # 尝试发送
            try:
                use_ssl = self.smtp_config.get("use_ssl", False)
                port = self.smtp_config.get("port", 587)

                if use_ssl and port == 465:
                    # QQ邮箱SSL模式
                    context = ssl.create_default_context()
                    server = smtplib.SMTP_SSL(host, port, context=context)
                    server.login(username, password)
                    server.sendmail(username, self.get_recipient(), msg.as_string())
                    server.quit()
                else:
                    # 普通TLS模式
                    server = smtplib.SMTP(host, port)
                    server.starttls()
                    server.login(username, password)
                    server.sendmail(username, self.get_recipient(), msg.as_string())
                    server.quit()
                
                return True, f"邮件发送成功！\n收件人: {self.get_recipient()}\n主题: {subject}"
            
            except smtplib.SMTPAuthenticationError:
                return False, "认证失败，请检查SMTP用户名和密码是否正确"
            except smtplib.SMTPException as e:
                return False, f"SMTP发送失败: {str(e)}"
        
        except Exception as e:
            return False, f"邮件发送失败: {str(e)}"
    
    def save_draft(self,
                  subject: str,
                  content: str,
                  report_type: str) -> str:
        """
        保存邮件草稿（用于调试或手动发送）
        """
        drafts_dir = f"{self.base_dir}/logs/drafts"
        os.makedirs(drafts_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{drafts_dir}/{report_type}_{timestamp}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"主题: {subject}\n")
            f.write(f"收件人: {self.get_recipient()}\n")
            f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("\n" + "="*60 + "\n\n")
            f.write(content)
        
        return filename


from typing import Tuple


# =============================================================================
# 便捷函数
# =============================================================================

def send_daily_report(content: str, attachment_path: str = None) -> Tuple[bool, str]:
    """发送每日复盘报告"""
    sender = EmailSender()
    date = datetime.now().strftime("%Y%m%d")
    subject = sender.generate_subject("复盘报告", date=date)
    return sender.send_email(subject, content, "复盘报告", attachment_path)


def send_dragon_pool(content: str, attachment_path: str = None) -> Tuple[bool, str]:
    """发送龙头股池"""
    sender = EmailSender()
    date = datetime.now().strftime("%Y%m%d")
    subject = sender.generate_subject("龙头股池", date=date)
    return sender.send_email(subject, content, "龙头股池", attachment_path)


def send_weekly_report(content: str, attachment_path: str = None) -> Tuple[bool, str]:
    """发送周度报告"""
    sender = EmailSender()
    now = datetime.now()
    subject = sender.generate_subject("周度报告", year=now.year, week=now.isocalendar()[1])
    return sender.send_email(subject, content, "周度报告", attachment_path)


def send_monthly_report(content: str, attachment_path: str = None) -> Tuple[bool, str]:
    """发送月度报告"""
    sender = EmailSender()
    now = datetime.now()
    subject = sender.generate_subject("月度报告", year=now.year, month=now.month)
    return sender.send_email(subject, content, "月度报告", attachment_path)


# =============================================================================
# 测试
# =============================================================================

if __name__ == "__main__":
    print("="*60)
    print("邮件发送模块测试")
    print("="*60)
    
    sender = EmailSender()
    
    print(f"\n收件人: {sender.get_recipient()}")
    print(f"主题格式:")
    for key, value in sender.subject_format.items():
        print(f"  {key}: {value}")
    
    # 测试生成主题
    test_subject = sender.generate_subject("龙头股池", date="20260511")
    print(f"\n测试主题: {test_subject}")
    
    print("\n提示: 实际发送邮件需要配置SMTP用户名和密码")
    print("请编辑 config/email_config.json 文件设置:")
    print('  "username": "your-email@gmail.com"')
    print('  "password": "your-app-password"')
