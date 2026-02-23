"""
Sage 300 ERP database client.

Queries the ISIDAT database for order line items (OEORDH -> OEORDD)
to provide SKU, description, and quantity data for ShipStation packing slips.

Auth: Windows (Trusted_Connection) or SQL Server (username/password).
Driver: ODBC Driver 17 for SQL Server.
"""

import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger("qpss")

try:
    import pyodbc
except ImportError:
    pyodbc = None
    logger.warning("pyodbc not installed — Sage 300 item lookup will be unavailable. "
                   "Install with: pip install pyodbc")


@dataclass
class OrderItem:
    """A single line item from Sage 300 OEORDD."""
    line_number: int = 0
    item_number: str = ""       # ITEM — the SKU
    description: str = ""       # DESC — item description
    qty_ordered: float = 0.0    # QTYORDERED
    qty_shipped: float = 0.0    # QTYSHIPPED (Sage 300 column name)
    unit_price: float = 0.0     # UNITPRICE


class SageConnectionError(Exception):
    """Raised when unable to connect to the Sage 300 database."""
    pass


class SageQueryError(Exception):
    """Raised when a query fails."""
    pass


class SageClient:
    """Client for querying Sage 300 ERP order data via ODBC."""

    def __init__(
        self,
        server: str,
        database: str,
        username: str = "",
        password: str = "",
        odbc_driver: str = "ODBC Driver 17 for SQL Server",
    ):
        if pyodbc is None:
            raise SageConnectionError(
                "pyodbc is not installed. Run: pip install pyodbc"
            )

        self.server = server
        self.database = database
        self.odbc_driver = odbc_driver

        # Build connection string
        if username:
            # SQL Server authentication
            self.conn_str = (
                f"DRIVER={{{odbc_driver}}};"
                f"SERVER={server};"
                f"DATABASE={database};"
                f"UID={username};"
                f"PWD={password};"
            )
            self._auth_mode = "SQL"
        else:
            # Windows authentication
            self.conn_str = (
                f"DRIVER={{{odbc_driver}}};"
                f"SERVER={server};"
                f"DATABASE={database};"
                f"Trusted_Connection=yes;"
            )
            self._auth_mode = "Windows"

    def test_connection(self) -> bool:
        """Test that we can connect to the database.

        Returns True on success, raises SageConnectionError on failure.
        """
        try:
            conn = pyodbc.connect(self.conn_str, timeout=10)
            conn.close()
            logger.info(f"Sage 300 DB connection OK ({self._auth_mode} auth, "
                        f"server={self.server}, db={self.database})")
            return True
        except Exception as e:
            raise SageConnectionError(
                f"Cannot connect to {self.server}/{self.database} "
                f"({self._auth_mode} auth): {e}"
            )

    def get_order_items(self, order_number: str) -> list[OrderItem]:
        """Look up line items for an order number.

        Args:
            order_number: The Sage 300 order number (e.g., 'ORD0469657').
                          This matches OEORDH.ORDNUMBER.

        Returns:
            List of OrderItem objects. Empty list if order not found.

        Raises:
            SageConnectionError: If unable to connect.
            SageQueryError: If the query itself fails.
        """
        try:
            conn = pyodbc.connect(self.conn_str, timeout=10)
        except Exception as e:
            raise SageConnectionError(
                f"Cannot connect to {self.server}/{self.database}: {e}"
            )

        try:
            cursor = conn.cursor()

            # Step 1: Get ORDUNIQ from the order header
            cursor.execute(
                "SELECT ORDUNIQ FROM dbo.OEORDH WHERE ORDNUMBER = ?",
                (order_number,)
            )
            row = cursor.fetchone()
            if not row:
                logger.debug(f"Order {order_number} not found in OEORDH")
                return []

            orduniq = row[0]
            logger.debug(f"Order {order_number} → ORDUNIQ={orduniq}")

            # Step 2: Get line items from order detail
            cursor.execute(
                """
                SELECT LINENUM, ITEM, [DESC], QTYORDERED, QTYSHIPPED, UNITPRICE
                FROM dbo.OEORDD
                WHERE ORDUNIQ = ?
                ORDER BY LINENUM
                """,
                (orduniq,)
            )

            items = []
            for row in cursor.fetchall():
                item = OrderItem(
                    line_number=int(row[0] or 0),
                    item_number=str(row[1] or "").strip(),
                    description=str(row[2] or "").strip(),
                    qty_ordered=float(row[3] or 0),
                    qty_shipped=float(row[4] or 0),
                    unit_price=float(row[5] or 0),
                )
                items.append(item)

            logger.debug(f"Order {order_number}: {len(items)} line item(s)")
            return items

        except SageConnectionError:
            raise
        except Exception as e:
            raise SageQueryError(f"Query failed for order {order_number}: {e}")
        finally:
            conn.close()
